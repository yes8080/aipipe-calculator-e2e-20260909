import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluate, Calculator } from '../src/calculator.mjs';
const input = sequence => { const c = new Calculator(); for (const key of sequence) c.input(key); return c; };
for (const [expression, expected] of [['2+3*4',14],['20/5*2',8],['10-3-2',5],['0.1+0.2',0.3],['-5+2',-3],['2*-3',-6],['2/-4',-0.5],['.5+.25',0.75],['-0',0],['1/3',0.333333333333],['12.5*2-5/2',22.5]]) {
  test(`${expression} = ${expected}`, () => assert.equal(evaluate(expression), expected));
}
for (const expression of ['', '1+', '1..2', 'Math.random()', '2(3)', '1e3', '1;alert(1)', '1/0', '0/0', '999999999999999*9']) {
  test(`reject ${JSON.stringify(expression)}`, () => assert.throws(() => evaluate(expression)));
}
test('entry honors precedence', () => assert.equal(input('2+3*4=').display, '14'));
test('decimal correction and repeated decimal', () => assert.equal(input('.1+.2.=').display, '0.3'));
test('negative entry after multiply', () => assert.equal(input('2*-3=').display, '-6'));
test('clear and backspace', () => { const c = input('123'); c.input('Backspace'); assert.equal(c.display,'12'); c.input('Escape'); assert.equal(c.display,'0'); c.input('4'); c.input('AC'); assert.equal(c.display,'0'); });
test('division error recovers on next digit', () => { const c = input('1/0='); assert.equal(c.display,'不能除以零'); c.input('7'); assert.equal(c.display,'7'); assert.equal(c.error,''); });
test('incomplete expression can be cleared', () => { const c = input('2+='); assert.equal(c.display,'算式不完整'); c.input('Backspace'); assert.equal(c.display,'0'); });
test('result then number starts fresh', () => assert.equal(input('2+3=7').display,'7'));
test('result then operator continues', () => assert.equal(input('2+3=*4=').display,'20'));
test('repeated equals keeps result', () => assert.equal(input('2+3===').display,'5'));
test('Enter evaluates', () => { const c = input('4/2'); c.input('Enter'); assert.equal(c.display,'2'); });
test('operator replacement', () => assert.equal(input('2+*3=').display,'6'));
test('ignores unsupported keys and initial operators', () => assert.equal(input('a*/+').display,'0'));
test('limits long input', () => assert.equal(input('1'.repeat(130)).expression.length,120));
test('small result can continue without unsupported exponent notation', () => assert.equal(input('1/10000000=*2=').display,'0.0000002'));

test('tiny supported values retain significant digits', () => assert.equal(input('1.23/1000000000000=').display,'0.00000000000123'));

test('Delete clears typed input, errors and completed results like Escape', () => {
  for (const sequence of ['123+4', '1/0=', '2+3=']) {
    const calculator = input(sequence);
    calculator.input('Delete');
    assert.equal(calculator.display, '0', sequence);
    assert.equal(calculator.error, '');
    assert.equal(calculator.result, false);
    calculator.input('7');
    assert.equal(calculator.display, '7');
  }
});
