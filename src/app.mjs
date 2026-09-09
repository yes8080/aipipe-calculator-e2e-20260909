import { Calculator } from './calculator.mjs';
const calculator = new Calculator();
const display = document.querySelector('#display');
const status = document.querySelector('#status');
function input(key) {
  calculator.input(key);
  display.textContent = calculator.display.replaceAll('*', '×').replaceAll('/', '÷');
  display.classList.toggle('error', Boolean(calculator.error));
  status.textContent = calculator.error ? '输入数字重新开始，或按清空' : calculator.result ? '计算完成' : '按 Enter 或等号计算';
}
document.querySelectorAll('button[data-key]').forEach(button => button.addEventListener('click', () => input(button.dataset.key)));
document.addEventListener('keydown', event => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (/^[\d.+*/=-]$/.test(event.key) || ['Enter', 'Escape', 'Backspace'].includes(event.key)) {
    event.preventDefault(); input(event.key);
  }
});
