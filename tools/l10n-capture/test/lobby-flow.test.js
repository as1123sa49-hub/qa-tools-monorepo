import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { isLoginGameUrl, parseLoginGamePayload } from '../lib/lobby-flow.js';

describe('lobby-flow login_game', () => {
  it('isLoginGameUrl', () => {
    assert.equal(isLoginGameUrl('https://api.example.com/login_game'), true);
    assert.equal(isLoginGameUrl('https://x.com/api/Login_Game?x=1'), true);
    assert.equal(isLoginGameUrl('https://x.com/add_recently_played'), false);
  });

  it('parseLoginGamePayload 成功', () => {
    const url = parseLoginGamePayload({
      status: '1',
      game_url: 'https://games-uat.comboburst.com/ProsperousTiger/?t=abc&l=bn',
    });
    assert.match(url, /ProsperousTiger/);
  });

  it('parseLoginGamePayload 字串 JSON', () => {
    const url = parseLoginGamePayload(
      '{"status":"1","game_url":"https://games-uat.comboburst.com/Foo/?l=en"}',
    );
    assert.match(url, /Foo/);
  });

  it('parseLoginGamePayload status 失敗', () => {
    assert.throws(
      () => parseLoginGamePayload({ status: '0', game_url: 'https://x.com/a' }),
      /login_game 失敗/,
    );
  });

  it('parseLoginGamePayload 缺 game_url', () => {
    assert.throws(() => parseLoginGamePayload({ status: '1' }), /缺少 game_url/);
  });
});
