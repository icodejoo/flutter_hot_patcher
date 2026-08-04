library hotpatch_validation.t08;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int op_arithmetic() => 3 + 4 * 2;  // T47: 11

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool op_comparison() => 15 >= 10;  // T48: true

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool op_logical() => true && false;  // T49: false

@pragma('vm:entry-point') @pragma('vm:never-inline')
int op_bitwise() => 12 & 10;  // T50: 8

class Vec2 {
  final int x, y;
  Vec2(this.x, this.y);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  Vec2 operator +(Vec2 other) => Vec2(x + other.x, y + other.y);
  @override String toString() => '($x,$y)';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String op_custom() => (Vec2(1, 2) + Vec2(3, 4)).toString();  // T51: (4,6)
