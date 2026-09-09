const MAX_LENGTH = 120;
export function evaluate(expression) {
  if (typeof expression !== 'string' || !expression.trim() || expression.length > MAX_LENGTH) throw new Error('请输入有效算式');
  const source = expression.replace(/\s/g, '');
  let cursor = 0;
  function number() {
    let sign = 1;
    if (source[cursor] === '+' || source[cursor] === '-') sign = source[cursor++] === '-' ? -1 : 1;
    const match = source.slice(cursor).match(/^(?:\d+(?:\.\d*)?|\.\d+)/);
    if (!match) throw new Error('算式不完整');
    cursor += match[0].length;
    return sign * Number(match[0]);
  }
  function product() {
    let value = number();
    while (source[cursor] === '*' || source[cursor] === '/') {
      const op = source[cursor++];
      const right = number();
      if (op === '/' && right === 0) throw new Error('不能除以零');
      value = op === '*' ? value * right : value / right;
    }
    return value;
  }
  let value = product();
  while (source[cursor] === '+' || source[cursor] === '-') {
    const op = source[cursor++];
    const right = product();
    value = op === '+' ? value + right : value - right;
  }
  if (cursor !== source.length) throw new Error('算式包含无效字符');
  if (!Number.isFinite(value) || Math.abs(value) >= 1e15 || (value !== 0 && Math.abs(value) < 1e-12)) throw new Error('结果超出支持范围');
  return Object.is(value, -0) ? 0 : Number(value.toPrecision(12));
}
function format(value) {
  if (value === 0) return '0';
  const places = Math.max(0, 11 - Math.floor(Math.log10(Math.abs(value))));
  return value.toFixed(places).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
}
export class Calculator {
  expression = '';
  result = false;
  error = '';
  input(key) {
    if (key === 'Escape' || key === 'AC') { this.expression = ''; this.result = false; this.error = ''; return; }
    if (key === 'Backspace') {
      this.expression = this.error ? '' : this.expression.slice(0, -1);
      this.error = ''; this.result = false; return;
    }
    if (key === 'Enter' || key === '=') {
      if (!this.expression || this.error || this.result) return;
      try { this.expression = format(evaluate(this.expression)); this.result = true; }
      catch (error) { this.error = error.message; }
      return;
    }
    if (!/^[\d.+*/-]$/.test(key)) return;
    if (this.error || (this.result && /[\d.]/.test(key))) this.expression = '';
    this.error = ''; this.result = false;
    if (this.expression.length >= MAX_LENGTH) return;
    if (/\d/.test(key)) { this.expression += key; return; }
    if (key === '.') {
      const current = this.expression.split(/[+*/-]/).at(-1);
      if (!current.includes('.')) this.expression += current ? '.' : '0.';
      return;
    }
    if (!this.expression) { if (key === '-') this.expression = '-'; return; }
    if (/[+*/-]$/.test(this.expression)) {
      if (key === '-' && /[*/]$/.test(this.expression)) this.expression += '-';
      else this.expression = this.expression.replace(/[+*/-]+$/, key);
    } else this.expression += key;
  }
  get display() { return this.error || this.expression || '0'; }
}
