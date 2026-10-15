import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeBaseUrl, safeSourceUrl } from '../src/connection.mjs';

test('trusted LAN and HTTPS endpoints accepted', () => {
  for (const host of ['192.168.1.20', '10.0.2.2', '172.16.0.2', '127.0.0.1', 'localhost']) {
    assert.equal(normalizeBaseUrl(`http://${host}:8000/`), `http://${host}:8000`);
  }
  assert.equal(normalizeBaseUrl(' https://example.com '), 'https://example.com');
});
test('public cleartext, credentials, and paths rejected', () => {
  for (const value of ['http://example.com', 'http://8.8.8.8', 'http://172.32.1.1', 'ftp://localhost', 'https://user:pass@example.com', 'https://example.com/api', 'https://example.com?x=1', 'https://example.com#secret', '']) {
    assert.throws(() => normalizeBaseUrl(value));
  }
});
test('source URLs cannot invoke scripts or leak local paths', () => {
  for (const source of ['javascript:alert(1)', 'file:///E:/test', 'knowledge/photo.md', '']) assert.equal(safeSourceUrl(source), null);
  assert.equal(safeSourceUrl('https://example.com/reference'), 'https://example.com/reference');
});
