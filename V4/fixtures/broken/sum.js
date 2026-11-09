/* A deliberately broken module. Nothing in this app requires it.
 *
 * It exists so the repair loop has something genuinely wrong to repair: `mean`
 * subtracts the count where it should divide by it, and the test below it fails
 * for that reason and no other. The loop copies this folder, edits the copy and
 * reruns the suite -- see V4/README.md for the command.
 */
'use strict';

function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}

/* mean([2, 4]) should be 3. It returns 4, because 6 - 2 is not an average. */
function mean(values) {
  if (!values.length) return 0;
  return sum(values) - values.length;
}

module.exports = { sum, mean };
