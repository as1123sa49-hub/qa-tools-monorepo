import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {
  sanitizeUserId,
  userRoot,
  userAuthPath,
  userOutputRoot,
} from '../lib/user-context.js';
import { TOOL_ROOT } from '../lib/config.js';

describe('user-context', () => {
  it('sanitizeUserId 空值為 default', () => {
    assert.equal(sanitizeUserId(''), 'default');
    assert.equal(sanitizeUserId(null), 'default');
    assert.equal(sanitizeUserId(undefined), 'default');
  });

  it('sanitizeUserId 過濾非法字元', () => {
    assert.equal(sanitizeUserId('alice'), 'alice');
    assert.equal(sanitizeUserId('bob.qa'), 'bob_qa');
    assert.equal(sanitizeUserId('../evil'), '___evil');
    assert.equal(sanitizeUserId('a/b\\c'), 'a_b_c');
  });

  it('userRoot 落在 data 下', () => {
    const root = userRoot('alice');
    assert.equal(root, path.join(TOOL_ROOT, 'data', 'alice'));
    assert.ok(!root.includes('..'));
  });

  it('userAuthPath / userOutputRoot 在工作區內', () => {
    const cfg = { authFile: '.auth/lobby.json', outputRoot: 'captures' };
    const uid = 'qa-01';
    const auth = userAuthPath(uid, cfg);
    const out = userOutputRoot(uid, cfg);
    assert.equal(auth, path.join(TOOL_ROOT, 'data', uid, '.auth', 'lobby.json'));
    assert.equal(out, path.join(TOOL_ROOT, 'data', uid, 'captures'));
    assert.ok(auth.startsWith(userRoot(uid)));
    assert.ok(out.startsWith(userRoot(uid)));
  });
});
