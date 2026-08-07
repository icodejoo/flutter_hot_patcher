// 取证基线样本。
// 刻意包含：字符串常量、虚调用（多实现）、tear-off、闭包，
// 以确保 object pool / dispatch table / DD table 三张表都非空。

abstract class Greeter {
  String greet();
}

class EnglishGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_EN';
}

class FrenchGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_FR';
}

class GermanGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_DE';
}

class SpanishGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_ES';
}

const kTag = 'TAG_AAAA';

int computeChecksum(int seed) {
  var acc = seed;
  for (var i = 0; i < 16; i++) {
    acc = (acc * 31 + i) & 0xFFFFFF;
  }
  return acc;
}

int computeSquare(int x) => x * x;

List<Greeter> makeGreeters() =>
    [EnglishGreeter(), FrenchGreeter(), GermanGreeter(), SpanishGreeter()];

void main(List<String> args) {
  final greeters = makeGreeters();
  // 虚调用：编译期不可静态解析，进入 dispatch table / DD table
  for (final g in greeters) {
    print('${g.greet()} $kTag');
  }
  // tear-off + 闭包
  final fn = computeChecksum;
  final wrapped = (int x) => fn(x) + 1;
  print(wrapped(args.length));
  print(computeSquare(args.length));
}
