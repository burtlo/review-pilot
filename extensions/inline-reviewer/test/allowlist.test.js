"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { matchesAllowlist } = require("../lib/allowlist.js");

test("an empty allowlist matches nothing", () => {
  assert.equal(matchesAllowlist("", "owner", "repo"), false);
  assert.equal(matchesAllowlist("   \r\n\n  ", "owner", "repo"), false);
  assert.equal(matchesAllowlist(null, "owner", "repo"), false);
});

test("owner/* matches one repo segment", () => {
  assert.equal(matchesAllowlist("owner/*", "owner", "repo"), true);
  assert.equal(matchesAllowlist("owner/*", "Owner", "Widget"), true);
  assert.equal(matchesAllowlist("Owner/*", "owner", "repo"), true);
  assert.equal(matchesAllowlist("owner/*", "other", "repo"), false);
  assert.equal(matchesAllowlist("owner/*", "owner", "repo/extra"), false);
  assert.equal(matchesAllowlist("owner2/*", "owner", "repo"), false);
});

test("*/* matches any owner and repo", () => {
  assert.equal(matchesAllowlist("*/*", "owner", "repo"), true);
  assert.equal(matchesAllowlist("*/*", "Other", "Repo"), true);
  assert.equal(matchesAllowlist("*/*", "kwik-trip-iot", "device-api"), true);
});

test("a non-matching repo is rejected", () => {
  assert.equal(matchesAllowlist("owner/*", "other", "repo"), false);
  assert.equal(matchesAllowlist("acme/widgets", "acme", "other"), false);
});

test("* does not cross a slash", () => {
  assert.equal(matchesAllowlist("*", "owner", "repo"), false);
  assert.equal(matchesAllowlist("owner*", "owner/repo", "app"), false);
  assert.equal(matchesAllowlist("kwik-trip-iot/*", "kwik-trip-iot", "device/api"), false);
  assert.equal(matchesAllowlist("kwik-trip-iot/*/*", "kwik-trip-iot", "device"), false);
  assert.equal(matchesAllowlist("kwik-*-iot/*", "Kwik-Trip-IOT", "device-api"), true);
  assert.equal(matchesAllowlist("kwik-trip-iot/*", "kwik-trip-iot-extra", "device-api"), false);
});

test("any listed line can match", () => {
  assert.equal(matchesAllowlist("nope/nope\nowner/*", "owner", "repo"), true);
});
