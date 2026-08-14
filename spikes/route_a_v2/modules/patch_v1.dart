import 'package:route_a_demo/greeting.dart' as greeting;

@pragma('dyn-module:entry-point')
void patchEntry() {
  greeting.impl = () => 'PATCHED_V1';
}
