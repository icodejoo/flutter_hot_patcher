library hotpatch_validation.t14;

// T74: B changes
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_2level() => 'b_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_2level() => '${prop_b_2level()}_via_a';  // unchanged body, but calls changed fn

// T75: C changes
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_3level() => 'c_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_3level() => '${prop_c_3level()}_b';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_3level() => '${prop_b_3level()}_a';

// T76: D changes
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_4level() => 'd_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_4level() => '${prop_d_4level()}_c';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_4level() => '${prop_c_4level()}_b';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_4level() => '${prop_b_4level()}_a';

// T77: Only B changes, C stays same
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_diamond() => 'b_diamond_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_diamond() => 'c_diamond_stable';  // UNCHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_diamond() => '${prop_b_diamond()}+${prop_c_diamond()}';

// T78: B and D both change
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_multi() => 'b_multi_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_multi() => 'd_multi_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_multi() => '${prop_b_multi()}+${prop_d_multi()}';

// T79: Only B changes, D unchanged
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_sibling() => 'b_sibling_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_sibling() => 'd_sibling_stable';   // UNCHANGED — must NOT appear in affected

// T80: ChainB changes
class ChainA {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String call() => ChainB().call();
}
class ChainB {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String call() => 'chain_b_patched';  // CHANGED
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_cross_class() => ChainA().call();

// T81: static_b changes
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_static_b() => 'static_b_patched';  // CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_static_a() => '${prop_static_b()}_a';

void main() {}
