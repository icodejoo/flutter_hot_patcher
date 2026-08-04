library hotpatch_validation.t14;

// T74: 2-level chain — A calls B, B changes → A in affected_closure
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_2level() => 'b_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_2level() => '${prop_b_2level()}_via_a';

// T75: 3-level chain — C changes → B,A in affected
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_3level() => 'c_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_3level() => '${prop_c_3level()}_b';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_3level() => '${prop_b_3level()}_a';

// T76: 4-level chain
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_4level() => 'd_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_4level() => '${prop_d_4level()}_c';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_4level() => '${prop_c_4level()}_b';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_4level() => '${prop_b_4level()}_a';

// T77: Diamond — A calls B and C; B changes, C stable → C NOT in changed
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_diamond() => 'b_diamond_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_diamond() => 'c_diamond_stable';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_diamond() => '${prop_b_diamond()}+${prop_c_diamond()}';

// T78: Multi-point — B and D both change simultaneously
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_multi() => 'b_multi_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_multi() => 'd_multi_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_multi() => '${prop_b_multi()}+${prop_d_multi()}';

// T79: Sibling — B changes; D doesn't call B, should NOT be affected
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_sibling() => 'b_sibling_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_sibling() => 'd_sibling_stable';

// T80: Cross-class call chain
class ChainA {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String call() => ChainB().call();
}
class ChainB {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String call() => 'chain_b_baseline';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_cross_class() => ChainA().call();

// T81: Static call chain
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_static_b() => 'static_b_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_static_a() => '${prop_static_b()}_a';

void main() {}
