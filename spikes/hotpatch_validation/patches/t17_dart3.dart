library hotpatch_validation.t17;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_records() {
  final point = (x: 10, y: 20);  // T92: ×10
  return '(${point.x},${point.y})';
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_pattern_switch() {
  final val = -1;  // T93: negative now
  return switch (val) {
    < 0 => 'negative',
    0 => 'zero',
    _ => 'positive',
  };
}

extension type Celsius(double value) {
  double toFahrenheit() => value * 9 / 5 + 32;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_extension_type() => Celsius(100.0).toFahrenheit().toString(); // T94: 100°C

sealed class Shape {}
class Circle extends Shape { final double r; Circle(this.r); }
class Square extends Shape { final double s; Square(this.s); }
double _area(Shape shape) => switch (shape) {
  Circle(:var r) => 3.14 * r * r,
  Square(:var s) => s * s,
};
@pragma('vm:entry-point') @pragma('vm:never-inline')
String dart3_sealed() => _area(Square(4.0)).toStringAsFixed(2); // T95: Square instead
void main() {}
