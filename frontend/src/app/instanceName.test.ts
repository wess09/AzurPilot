import { describe, expect, it } from 'vitest'
import { INSTANCE_NAME_PATTERN } from './instanceName'

// 浏览器按 v 标志编译 HTML pattern 属性：编译失败时属性会被整条忽略，
// 校验会静默退化。这里用同一标志编译，确保规则真的生效。
const rule = new RegExp(`^(?:${INSTANCE_NAME_PATTERN})$`, 'v')
// 与后端 validate_name 同一顺序：先归一化首尾空白与点，再让正则判定。
const validate = (name: string) => rule.test(name.trimStart().replace(/[\s.]+$/, ''))

// 接受名单里特意包含数字开头、点号与空格——这些在上游都是合法配置文件名。
const accepted = ['测试', '测试实例', 'alas测试', '測試', '测试-2', 'a', 'A1_b-c', 'x'.repeat(64),
  '2ap', '12zz', 'zz.v2', 'ap 2', '测试.1', '1测试',
  'テスト', 'テスト2', 'アズール', 'ひらがな', 'ｱｽﾞｰﾙ']
// 拒绝的全是安全边界：路径字符、不用 dotAll 时 `.` 会漏过的换行、超出长度、首尾点。
const rejected = ['测试/实例', '测试\\实例', 'a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a>b', 'a|b',
  'a\nb', 'a\tb', '', ' '.repeat(3), '.', '..', '.hidden', '-测试', '测试#1', 'x'.repeat(65)]

describe('实例名规则', () => {
  it('能在 v 标志下编译', () => {
    expect(() => new RegExp(`^(?:${INSTANCE_NAME_PATTERN})$`, 'v')).not.toThrow()
  })
  it('接受数字开头、点号、空格与汉字，拒绝路径字符与首尾点', () => {
    for (const name of accepted) expect(validate(name), `应接受 ${name}`).toBe(true)
    for (const name of rejected) expect(validate(name), `应拒绝 ${name}`).toBe(false)
  })
})
