'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { sum, mean } = require('./sum.js');

test('sum adds the values', () => {
  assert.equal(sum([2, 3]), 5);
});

test('mean averages the values', () => {
  assert.equal(mean([2, 4]), 3);
  assert.equal(mean([1, 2, 3, 4]), 2.5);
});
