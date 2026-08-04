library hotpatch_validation.t09;

@pragma('dyn-module:entry-point')
String async_await_chain() => 'step1->step3->done';
