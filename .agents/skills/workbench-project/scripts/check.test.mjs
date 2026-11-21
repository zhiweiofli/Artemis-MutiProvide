import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { snapshot, doctor, verifyHandoff, checkEnv, digest } from './check.mjs';

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'awb-check-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, '.agent'));
  await mkdir(join(root, '.local'));
  const contract = { schema_version: 1, project: 'fixture',
    documents: ['identity', 'rules', 'navigation', 'acceptance', 'handoff'].map(role => ({ role, path: 'README.md' })),
    validation: [{ command: 'node checker doctor .', source: 'README.md' }] };
  await writeFile(join(root, 'README.md'), 'Fixture contract and validation source\n');
  await writeFile(join(root, '.agent/contract.json'), JSON.stringify(contract));
  const baseline = await snapshot(root, ['README.md', '.agent', 'new.md']);
  const raw = JSON.stringify(baseline);
  await writeFile(join(root, '.local/baseline.json'), raw);
  const handoff = { schema_version: 1, goal: 'Verify fixture', scope: ['README.md', 'new.md', 'outside.md'], acceptance_criteria: ['References resolve'],
    workspace: { path: baseline.root, head: null, dirty: true }, baseline: { path: '.local/baseline.json', sha256: digest(raw) },
    changes: [], context: Object.entries(baseline.files).map(([path, sha256]) => ({ path, sha256 })),
    evidence: [{ path: 'README.md', sha256: baseline.files['README.md'], command: 'read fixture', result: 'read' }],
    decisions: [], open_questions: [], acceptance: { local_verification: 'passed', production_deployment: 'N/A', real_client_acceptance: 'pending', human_acceptance: 'pending' } };
  const file = join(root, '.local/handoff.json');
  const save = () => writeFile(file, JSON.stringify(handoff));
  await save();
  return { root, handoff, file, save, contract };
}

test('dirty workspace without a commit supports doctor and consistent handoff', async t => {
  const f = await fixture(t);
  assert.equal((await doctor(f.root)).status, 'healthy');
  const result = await verifyHandoff(f.root, f.file);
  assert.equal(result.status, 'passed');
  assert.equal(result.preserved_files, 2);
});
test('doctor reports a moved or missing document', async t => {
  const f = await fixture(t);
  f.contract.documents[0].path = 'missing.md';
  await writeFile(join(f.root, '.agent/contract.json'), JSON.stringify(f.contract));
  assert.equal((await doctor(f.root)).status, 'degraded');
});
test('context drift is rejected after a file changes', async t => {
  const f = await fixture(t);
  const content = 'New fixture\n';
  await writeFile(join(f.root, 'README.md'), content);
  f.handoff.changes = [{ path: 'README.md', before_sha256: f.handoff.context.find(x => x.path === 'README.md').sha256, after_sha256: digest(content) }];
  await f.save();
  await assert.rejects(verifyHandoff(f.root, f.file), /context digest mismatch/);
});
test('an unreported new file in the declared scope is rejected', async t => {
  const f = await fixture(t);
  await writeFile(join(f.root, 'new.md'), 'Unreported\n');
  await assert.rejects(verifyHandoff(f.root, f.file), /Unreported change/);
});
test('reported additions and deletions are verified against the baseline', async t => {
  const f = await fixture(t);
  await writeFile(join(f.root, 'new.md'), 'Added\n');
  f.handoff.changes.push({ path: 'new.md', before_sha256: null, after_sha256: digest('Added\n') });
  await f.save();
  assert.equal((await verifyHandoff(f.root, f.file)).changes, 1);
  await rm(join(f.root, 'new.md'));
  await assert.rejects(verifyHandoff(f.root, f.file), /After digest mismatch/);
});
test('missing required context or an acceptance layer fails', async t => {
  const f = await fixture(t);
  f.handoff.context = f.handoff.context.filter(item => item.path !== '.agent/contract.json');
  await f.save();
  await assert.rejects(verifyHandoff(f.root, f.file), /Missing handoff context/);
  delete f.handoff.acceptance.human_acceptance;
  await f.save();
  await assert.rejects(verifyHandoff(f.root, f.file), /Missing acceptance layer/);
});
test('paths outside the project and symlinks are not followed', async t => {
  const f = await fixture(t);
  await assert.rejects(snapshot(f.root, ['../outside']), /Invalid project path/);
  await symlink(join(f.root, 'README.md'), join(f.root, 'linked.md'));
  await assert.rejects(snapshot(f.root, ['linked.md']), /Symlink not supported/);
});
test('tampered baseline and claims outside coverage are rejected', async t => {
  const f = await fixture(t);
  await writeFile(join(f.root, 'outside.md'), 'No baseline\n');
  f.handoff.changes = [{ path: 'outside.md', before_sha256: null, after_sha256: digest('No baseline\n') }];
  await f.save();
  await assert.rejects(verifyHandoff(f.root, f.file), /outside baseline coverage/);
  await writeFile(join(f.root, '.local/baseline.json'), '{}');
  await assert.rejects(verifyHandoff(f.root, f.file), /Baseline digest mismatch/);
});
test('a declared delta cannot expand the work order scope', async t => {
  const f = await fixture(t);
  await writeFile(join(f.root, 'new.md'), 'Added\n');
  f.handoff.scope = ['README.md'];
  f.handoff.changes = [{ path: 'new.md', before_sha256: null, after_sha256: digest('Added\n') }];
  await f.save();
  await assert.rejects(verifyHandoff(f.root, f.file), /outside handoff scope/);
});
test('snapshot excludes runtime/credentials and leaves originals untouched', async t => {
  const f = await fixture(t);
  await writeFile(join(f.root, '.local/private.json'), 'private');
  await writeFile(join(f.root, '.env'), 'fixture-secret');
  const before = await readFile(join(f.root, 'README.md'));
  const result = await snapshot(f.root, ['README.md', '.local', '.env']);
  assert.deepEqual(Object.keys(result.files), ['README.md']);
  assert.deepEqual(await readFile(join(f.root, 'README.md')), before);
});
test('checkEnv detects project profiles, recommended tools and sensed dependencies', async t => {
  const f = await fixture(t);
  const binDir = join(f.root, '.local/bin');
  const homeDir = join(f.root, '.local/home');
  const sdkDir = join(f.root, '.local/mock-sdk');
  await mkdir(binDir, { recursive: true });
  await mkdir(sdkDir, { recursive: true });
  await mkdir(join(homeDir, '.agents/skills/archify'), { recursive: true });
  for (const name of ['semble', 'codegraph', 'gh', 'java', 'python3']) {
    await writeFile(join(binDir, name), '#!/bin/sh\n', { mode: 0o755 });
  }
  await writeFile(join(homeDir, '.agents/skills/archify/SKILL.md'), '---\nname: archify\n---\n');
  await writeFile(join(f.root, 'build.gradle'), '// gradle');
  await writeFile(join(f.root, 'gradlew'), '#!/bin/sh\n', { mode: 0o755 });
  await writeFile(join(f.root, 'local.properties'), `sdk.dir=${sdkDir}\n`);
  await mkdir(join(f.root, 'analysis'), { recursive: true });
  await mkdir(join(f.root, '.git/hooks'), { recursive: true });

  const env1 = await checkEnv(f.root, { pathDirs: [binDir], homeDir, env: {} });
  assert.deepEqual(env1.matched_profiles, ['general', 'code-engineering', 'research']);
  const byId1 = Object.fromEntries(env1.recommended_tools.map(x => [x.id, x]));
  assert.equal(byId1.semble.status, 'ready');
  assert.equal(byId1.codegraph.status, 'needs_project_init');
  assert.equal(byId1.gh.status, 'ready');
  assert.equal(byId1.archify.status, 'ready');
  assert.ok(env1.sensed_dependencies.some(d => d.id === 'jvm-gradle' && d.status === 'ready'));
  assert.ok(env1.sensed_dependencies.some(d => d.id === 'android-sdk' && d.status === 'ready'));

  await mkdir(join(f.root, '.codegraph'), { recursive: true });
  await writeFile(join(f.root, '.codegraph/index.db'), 'sqlite');
  await writeFile(join(f.root, '.mcp.json'), '{"mcpServers":{"codegraph":{"command":"codegraph","args":["serve","--mcp"]}}}');
  await writeFile(join(f.root, '.git/hooks/post-commit'), '#!/bin/sh\ncodegraph sync --quiet .\n', { mode: 0o755 });
  const env2 = await checkEnv(f.root, { pathDirs: [binDir], homeDir, env: {} });
  const byId2 = Object.fromEntries(env2.recommended_tools.map(x => [x.id, x]));
  assert.equal(byId2.codegraph.status, 'ready');
});
test('checkEnv rejects missing archify skill, non-executable java/gradlew/hooks, invalid sdk.dir and unconfigured mcp', async t => {
  const f = await fixture(t);
  const emptyBin = join(f.root, '.local/empty-bin');
  const emptyHome = join(f.root, '.local/empty-home');
  await mkdir(emptyBin, { recursive: true });
  await mkdir(emptyHome, { recursive: true });

  // Negative case 1: empty project, empty homeDir, empty pathDirs -> archify and semble must be missing_install, never ready
  const emptyEnv = await checkEnv(f.root, { pathDirs: [emptyBin], homeDir: emptyHome, env: {} });
  const emptyTools = Object.fromEntries(emptyEnv.recommended_tools.map(x => [x.id, x]));
  assert.equal(emptyTools.archify.status, 'missing_install');
  assert.equal(emptyTools.semble.status, 'missing_install');
  assert.ok(Array.isArray(emptyEnv.limits) && emptyEnv.limits.length > 0);

  // Negative case 2: java and gradlew exist as non-executable regular files (0o644) -> jvm-gradle must be needs_setup
  await writeFile(join(emptyBin, 'java'), 'not executable', { mode: 0o644 });
  await writeFile(join(f.root, 'build.gradle'), '// gradle');
  await writeFile(join(f.root, 'gradlew'), '#!/bin/sh\n', { mode: 0o644 });

  // Negative case 3: local.properties sdk.dir points to a non-existent directory -> android-sdk must be needs_setup
  await writeFile(join(f.root, 'local.properties'), `sdk.dir=${join(f.root, '.local/missing-android-sdk')}\n`);

  const badRuntimeEnv = await checkEnv(f.root, { pathDirs: [emptyBin], homeDir: emptyHome, env: {} });
  const depsById = Object.fromEntries(badRuntimeEnv.sensed_dependencies.map(d => [d.id, d]));
  assert.equal(depsById['jvm-gradle'].status, 'needs_setup');
  assert.equal(depsById['android-sdk'].status, 'needs_setup');
  assert.equal(depsById['android-sdk'].configured, false);

  // Adjacent negative case 4: codegraph binary executable, but .mcp.json lacks codegraph entry and post-commit hook is not executable
  await writeFile(join(emptyBin, 'codegraph'), '#!/bin/sh\n', { mode: 0o755 });
  await mkdir(join(f.root, '.codegraph'), { recursive: true });
  await writeFile(join(f.root, '.codegraph/index.db'), 'db');
  await writeFile(join(f.root, '.mcp.json'), '{"mcpServers":{}}');
  await mkdir(join(f.root, '.git/hooks'), { recursive: true });
  await writeFile(join(f.root, '.git/hooks/post-commit'), '#!/bin/sh\ncodegraph sync --quiet .\n', { mode: 0o644 });
  const badCgEnv = await checkEnv(f.root, { pathDirs: [emptyBin], homeDir: emptyHome, env: {} });
  const cgTool = badCgEnv.recommended_tools.find(x => x.id === 'codegraph');
  assert.equal(cgTool.status, 'needs_project_init');
});
