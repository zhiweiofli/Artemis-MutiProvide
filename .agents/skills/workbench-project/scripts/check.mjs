import { readFile, readdir, lstat, stat, access, constants, realpath, writeFile } from 'node:fs/promises';
import { resolve, relative, isAbsolute, sep, delimiter, join } from 'node:path';
import { createHash } from 'node:crypto';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';

export const digest = data => createHash('sha256').update(data).digest('hex');
const requiredRoles = ['identity', 'rules', 'navigation', 'acceptance', 'handoff'];
const skip = new Set(['.git', '.local', '.codegraph', 'node_modules']);
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const nonempty = value => typeof value === 'string' && value.trim().length > 0;
const assert = (condition, message) => { if (!condition) throw new Error(message); };

async function projectPath(root, name, missing = false) {
  assert(nonempty(name) && !isAbsolute(name) && !name.split(/[\\/]/).includes('..'), `Invalid project path: ${name}`);
  const path = resolve(root, name);
  assert(path !== root && !relative(root, path).startsWith(`..${sep}`), `Path outside project: ${name}`);
  let current = root;
  for (const part of relative(root, path).split(sep)) {
    current = resolve(current, part);
    try { assert(!(await lstat(current)).isSymbolicLink(), `Symlink not supported: ${name}`); }
    catch (error) { if (missing && error.code === 'ENOENT') return path; throw error; }
  }
  return path;
}

async function bytes(root, name) { return readFile(await projectPath(root, name)); }
async function fileHash(root, name, missing = false) {
  try { return digest(await readFile(await projectPath(root, name, missing))); }
  catch (error) { if (missing && error.code === 'ENOENT') return null; throw error; }
}

export async function snapshot(project, paths) {
  const root = await realpath(project);
  assert(Array.isArray(paths) && paths.length > 0, 'Snapshot requires explicit paths');
  const files = {};
  async function visit(name) {
    if (name.split('/').some(part => skip.has(part) || part === '.env' || part.startsWith('.env.'))) return;
    const path = await projectPath(root, name, true);
    let stat;
    try { stat = await lstat(path); }
    catch (error) { if (error.code === 'ENOENT') return; throw error; }
    if (stat.isDirectory()) {
      for (const entry of (await readdir(path)).sort()) await visit(`${name}/${entry}`);
    } else {
      assert(stat.isFile(), `Not a regular file: ${name}`);
      files[name] = await fileHash(root, name);
    }
  }
  for (const name of paths) { await projectPath(root, name, true); await visit(name); }
  return { schema_version: 1, root, paths, files };
}

export async function doctor(project) {
  const root = await realpath(project);
  const checks = [];
  try {
    const contract = JSON.parse(await bytes(root, '.agent/contract.json'));
    assert(contract.schema_version === 1 && nonempty(contract.project), 'Unsupported or incomplete project contract');
    assert(Array.isArray(contract.documents), 'documents must be an array');
    for (const role of requiredRoles) assert(contract.documents.some(doc => doc.role === role), `Missing role: ${role}`);
    assert(Array.isArray(contract.validation) && contract.validation.length > 0, 'Missing validation sources');
    for (const doc of contract.documents) {
      await bytes(root, doc.path);
      checks.push({ check: `document:${doc.role}`, status: 'passed', path: doc.path });
    }
    for (const item of contract.validation) {
      assert(nonempty(item.command), 'Missing validation command');
      await bytes(root, item.source);
      checks.push({ check: 'validation-source', status: 'passed', path: item.source, command: item.command });
    }
  } catch (error) { checks.push({ check: 'contract', status: 'failed', reason: error.message }); }
  return { status: checks.some(item => item.status === 'failed') ? 'degraded' : 'healthy', checks,
    limits: ['Read-only path/source checks; commands are not executed', 'Rule semantics, model login and automatic discovery are not verified'] };
}

export async function verifyHandoff(project, handoffFile) {
  const root = await realpath(project);
  const handoff = JSON.parse(await readFile(handoffFile));
  assert(handoff.schema_version === 1 && nonempty(handoff.goal), 'Unsupported or incomplete handoff');
  for (const key of ['scope', 'acceptance_criteria']) {
    assert(Array.isArray(handoff[key]) && handoff[key].length > 0 && handoff[key].every(nonempty), `Missing ${key}`);
  }
  assert(handoff.workspace?.path === root && typeof handoff.workspace.dirty === 'boolean', 'Workspace mismatch');
  assert(handoff.workspace.head === null || nonempty(handoff.workspace.head), 'Missing workspace head');
  for (const key of ['decisions', 'open_questions']) assert(Array.isArray(handoff[key]) && handoff[key].every(nonempty), `Invalid ${key}`);
  const states = ['passed', 'failed', 'pending', 'N/A'];
  for (const key of ['local_verification', 'production_deployment', 'real_client_acceptance', 'human_acceptance']) {
    assert(states.includes(handoff.acceptance?.[key]), `Missing acceptance layer: ${key}`);
  }
  assert(sha(handoff.baseline?.sha256), 'Missing baseline hash');
  const baselineBytes = await bytes(root, handoff.baseline.path);
  assert(digest(baselineBytes) === handoff.baseline.sha256, 'Baseline digest mismatch');
  const baseline = JSON.parse(baselineBytes);
  assert(baseline.schema_version === 1 && baseline.root === root, 'Baseline workspace mismatch');
  const current = await snapshot(root, baseline.paths);
  assert(Array.isArray(handoff.changes), 'Missing changes');
  const changes = new Map();
  for (const change of handoff.changes) {
    await projectPath(root, change.path, true);
    assert(handoff.scope.some(path => change.path === path || change.path.startsWith(`${path}/`)), `Change outside handoff scope: ${change.path}`);
    assert(baseline.paths.some(path => change.path === path || change.path.startsWith(`${path}/`)), `Change outside baseline coverage: ${change.path}`);
    assert(!changes.has(change.path), `Duplicate change: ${change.path}`);
    for (const key of ['before_sha256', 'after_sha256']) assert(change[key] === null || sha(change[key]), `Invalid ${key}: ${change.path}`);
    assert(change.before_sha256 !== change.after_sha256, `Unchanged delta: ${change.path}`);
    assert((baseline.files[change.path] ?? null) === change.before_sha256, `Before digest mismatch: ${change.path}`);
    assert(await fileHash(root, change.path, true) === change.after_sha256, `After digest mismatch: ${change.path}`);
    changes.set(change.path, change);
  }
  // The baseline defines the preservation claim; unrelated private/runtime data is not read.
  for (const name of new Set([...Object.keys(baseline.files), ...Object.keys(current.files)])) {
    if ((baseline.files[name] ?? null) !== (current.files[name] ?? null)) assert(changes.has(name), `Unreported change: ${name}`);
  }
  const checked = {};
  for (const key of ['context', 'evidence']) {
    assert(Array.isArray(handoff[key]) && handoff[key].length > 0, `Missing ${key}`);
    for (const item of handoff[key]) {
      assert(sha(item.sha256) && await fileHash(root, item.path) === item.sha256, `${key} digest mismatch: ${item.path}`);
      if (key === 'evidence') assert(nonempty(item.command) && nonempty(item.result), 'Evidence must describe the actual command and result');
    }
    checked[key] = handoff[key].length;
  }
  const contract = JSON.parse(await bytes(root, '.agent/contract.json'));
  const contextPaths = new Set(handoff.context.map(item => item.path));
  for (const name of ['.agent/contract.json', ...contract.documents.filter(doc => requiredRoles.includes(doc.role)).map(doc => doc.path)]) {
    assert(contextPaths.has(name), `Missing handoff context: ${name}`);
  }
  assert((await doctor(root)).status === 'healthy', 'Project doctor failed');
  return { status: 'passed', changes: changes.size, ...checked, baseline_paths: baseline.paths,
    preserved_files: Object.keys(baseline.files).filter(name => !changes.has(name)).length,
    limits: ['Hash/structure consistency only; evidence authenticity and task semantics require independent review', 'Preservation is limited to explicit baseline paths'] };
}

async function pathExists(target) {
  try { await stat(target); return true; }
  catch { return false; }
}

async function isRegularFile(target) {
  try { return (await stat(target)).isFile(); }
  catch { return false; }
}

async function isDirectory(target) {
  try { return (await stat(target)).isDirectory(); }
  catch { return false; }
}

async function isExecutableFile(target) {
  try {
    const s = await stat(target);
    if (!s.isFile()) return false;
    if (process.platform !== 'win32' && (s.mode & 0o111) === 0) return false;
    await access(target, constants.X_OK);
    return true;
  } catch { return false; }
}

async function findBinary(name, extraDirs = []) {
  const dirs = new Set([
    ...(process.env.PATH || '').split(delimiter).filter(Boolean),
    join(homedir(), '.local', 'bin'),
    '/opt/homebrew/bin',
    '/usr/local/bin'
  ]);
  for (const dir of [...extraDirs, ...dirs]) {
    const candidate = join(dir, name);
    if (await isExecutableFile(candidate)) return candidate;
  }
  return null;
}

function parseSdkDir(content, root) {
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^sdk\.dir\s*=\s*(.+)$/);
    if (match) {
      const unescaped = match[1].trim().replace(/\\:/g, ':').replace(/\\\\/g, '\\');
      return isAbsolute(unescaped) ? unescaped : resolve(root, unescaped);
    }
  }
  return null;
}

export async function checkEnv(project, options = {}) {
  const root = await realpath(project);
  const registryUrl = new URL('../references/recommended-tools.json', import.meta.url);
  const registry = JSON.parse(await readFile(registryUrl, 'utf8'));
  const home = options.homeDir ? await realpath(options.homeDir) : homedir();
  const env = options.env ?? process.env;
  const expandHome = p => p.startsWith('~/') ? join(home, p.slice(2)) : resolve(root, p);
  const resolveBinary = async bin => {
    if (options.pathDirs) {
      for (const d of options.pathDirs) {
        const c = join(d, bin);
        if (await isExecutableFile(c)) return c;
      }
      return null;
    }
    return findBinary(bin);
  };

  const matchedProfiles = [];
  for (const [id, profile] of Object.entries(registry.project_profiles || {})) {
    let matched = Boolean(profile.always_match);
    if (!matched) {
      for (const marker of profile.markers || []) {
        if (await pathExists(resolve(root, marker))) { matched = true; break; }
      }
    }
    if (matched) matchedProfiles.push(id);
  }

  const tools = [];
  for (const tool of registry.recommended_tools || []) {
    if (!tool.profiles.some(p => matchedProfiles.includes(p))) continue;
    const det = tool.detect || {};
    const hasBinaries = Array.isArray(det.binaries) && det.binaries.length > 0;
    const hasSkills = (Array.isArray(det.project_skills) && det.project_skills.length > 0)
      || (Array.isArray(det.global_skills) && det.global_skills.length > 0);

    const foundBinaries = {};
    let binaryOk = true;
    for (const bin of det.binaries || []) {
      const loc = await resolveBinary(bin);
      foundBinaries[bin] = loc;
      if (!loc) binaryOk = false;
    }

    const foundProjectSkills = [];
    for (const rel of det.project_skills || []) {
      if (await isRegularFile(resolve(root, rel))) foundProjectSkills.push(rel);
    }
    const foundGlobalSkills = [];
    for (const raw of det.global_skills || []) {
      if (await isRegularFile(expandHome(raw))) foundGlobalSkills.push(raw);
    }
    const skillOk = !hasSkills || foundProjectSkills.length > 0 || foundGlobalSkills.length > 0;

    const missingProjectPaths = [];
    for (const rel of det.project_paths || []) {
      const target = resolve(root, rel);
      if (rel === '.codegraph') {
        const dirOk = await isDirectory(target) && (await readdir(target)).length > 0;
        if (!dirOk) missingProjectPaths.push(rel);
      } else if (rel === '.mcp.json') {
        let mcpOk = false;
        try {
          const parsed = JSON.parse(await readFile(target, 'utf8'));
          mcpOk = nonempty(parsed?.mcpServers?.[tool.id]?.command);
        } catch { mcpOk = false; }
        if (!mcpOk) missingProjectPaths.push(rel);
      } else if (!(await pathExists(target))) {
        missingProjectPaths.push(rel);
      }
    }

    let gitHookOk = true;
    if (det.git_hook && await isDirectory(resolve(root, '.git'))) {
      const hookPath = resolve(root, det.git_hook.path);
      try {
        const execOk = await isExecutableFile(hookPath);
        const text = execOk ? await readFile(hookPath, 'utf8') : '';
        gitHookOk = execOk && (!det.git_hook.contains || text.includes(det.git_hook.contains));
      } catch { gitHookOk = false; }
    }

    const hostInstalled = (hasBinaries ? binaryOk : true) && (hasSkills && !hasBinaries ? skillOk : true);
    const projectInitialized = missingProjectPaths.length === 0 && gitHookOk;
    const status = !hostInstalled ? 'missing_install' : (!projectInitialized ? 'needs_project_init' : 'ready');

    tools.push({
      id: tool.id,
      name: tool.name,
      kind: tool.kind,
      status,
      binaries: foundBinaries,
      project_skills: foundProjectSkills,
      global_skills: foundGlobalSkills,
      missing_project_paths: missingProjectPaths,
      git_hook_ready: gitHookOk,
      unverified: tool.unverified || 'Static check only; runtime execution and host auto-discovery are not verified',
      install_guide: tool.install_guide,
      init_action: tool.init_action,
      policy: tool.policy
    });
  }

  const sensedDependencies = [];
  for (const det of registry.environment_detectors || []) {
    const matchedMarkers = [];
    for (const marker of det.markers || []) {
      if (await pathExists(resolve(root, marker))) matchedMarkers.push(marker);
    }
    if (matchedMarkers.length === 0) continue;

    const binaries = {};
    let ok = true;
    for (const bin of det.binaries || []) {
      const loc = await resolveBinary(bin);
      binaries[bin] = loc;
      if (!loc) ok = false;
    }
    const missingFiles = [];
    const execSet = new Set(det.executable_files || ['gradlew']);
    for (const rel of det.project_files || []) {
      const target = resolve(root, rel);
      const valid = execSet.has(rel) ? await isExecutableFile(target) : await isRegularFile(target);
      if (!valid) missingFiles.push(rel);
    }

    let configured = true;
    if (det.id === 'android-sdk') {
      let sdkValid = false;
      const localProps = resolve(root, 'local.properties');
      if (await isRegularFile(localProps)) {
        const sdkPath = parseSdkDir(await readFile(localProps, 'utf8'), root);
        sdkValid = Boolean(sdkPath && await isDirectory(sdkPath));
      } else {
        for (const key of det.env_vars || []) {
          if (nonempty(env[key]) && await isDirectory(env[key])) { sdkValid = true; break; }
        }
      }
      configured = sdkValid;
      ok = ok && sdkValid;
    } else {
      if (det.file_contains) {
        try {
          const content = await readFile(resolve(root, det.file_contains.path), 'utf8');
          configured = content.includes(det.file_contains.pattern);
        } catch { configured = false; }
      }
      ok = ok && missingFiles.length === 0 && configured;
    }

    sensedDependencies.push({
      id: det.id,
      label: det.label,
      status: ok ? 'ready' : 'needs_setup',
      matched_markers: matchedMarkers,
      binaries,
      missing_files: missingFiles,
      configured,
      remediation: det.remediation
    });
  }

  return {
    status: 'passed',
    project: root,
    matched_profiles: matchedProfiles,
    recommended_tools: tools,
    sensed_dependencies: sensedDependencies,
    limits: [
      'Static filesystem and PATH checks only; binaries, builds, MCP servers and git hooks are not executed',
      'ready indicates static executable/config/path presence, not live authentication (e.g. gh auth), MCP host discovery or runtime execution'
    ]
  };
}

async function main() {
  const [command, project, output, ...paths] = process.argv.slice(2);
  assert(project, 'Usage: check.mjs doctor PROJECT | env PROJECT | snapshot PROJECT OUTPUT PATH... | verify PROJECT HANDOFF');
  let result;
  if (command === 'doctor') result = await doctor(project);
  else if (command === 'env') result = await checkEnv(project);
  else if (command === 'snapshot') {
    assert(output, 'Missing output path');
    result = await snapshot(project, paths);
    await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, { flag: 'wx' });
    result = { status: 'passed', files: Object.keys(result.files).length, output: resolve(output), paths };
  } else if (command === 'verify') { assert(output, 'Missing handoff path'); result = await verifyHandoff(project, output); }
  else throw new Error('Unknown command');
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (result.status === 'degraded') process.exitCode = 1;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { process.stderr.write(`${JSON.stringify({ status: 'failed', reason: error.message })}\n`); process.exitCode = 1; });
}
