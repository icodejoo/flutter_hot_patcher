library hotpatch_validation.t17;

// T92: Records (named tuples, Dart 3.0)
@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_records() {
  final point = (x: 1, y: 2);
  return '(${point.x},${point.y})';
}

// T93: Pattern matching with switch
@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_pattern_switch() {
  final val = 42;
  return switch (val) {
    < 0 => 'negative',
    0 => 'zero',
    _ => 'positive',
  };
}

// T94: Extension type (Dart 3.3)
extension type Celsius(double value) {
  double toFahrenheit() => value * 9 / 5 + 32;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_extension_type() => Celsius(0.0).toFahrenheit().toString();

// T95: Sealed class + exhaustive switch
sealed class Shape {}
class Circle extends Shape { final double r; Circle(this.r); }
class Square extends Shape { final double s; Square(this.s); }
double _area(Shape shape) => switch (shape) {
  Circle(:var r) => 3.14 * r * r,
  Square(:var s) => s * s,
};
@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_sealed() => _area(Circle(1.0)).toStringAsFixed(2);

void main() {}
