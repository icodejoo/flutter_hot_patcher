library hotpatch_validation.t09;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_future_value() => '99';                  // T52

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_await_chain() => 'step1->step3->done';   // T53

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_future_error() => 'error:NewError';      // T54

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_stream() => '[10, 20, 30]';              // T55

void main() {}
