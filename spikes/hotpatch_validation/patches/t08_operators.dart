library hotpatch_validation.t08;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int op_arithmetic() => 3 * 4 + 2;  // T47: 14

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool op_comparison() => 5 >= 10;   // T48: false

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool op_logical() => true || false; // T49: true

@pragma('vm:entry-point') @pragma('vm:never-inline')
int op_bitwise() => 12 | 10;       // T50: 14

class Vec2 {
  final int x, y;
  Vec2(this.x, this.y);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  Vec2 operator +(Vec2 other) => Vec2(x - other.x, y - other.y);  // T51: subtract
  @override String toString() => '($x,$y)';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String op_custom() => (Vec2(5, 6) + Vec2(3, 4)).toString();  // (2,2)
void main() {}
