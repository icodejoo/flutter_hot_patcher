library hotpatch_validation.harness;

class TestCase {
  final String id;
  final String description;
  final String category;
  final String Function() baselineFn;
  TestCase(this.id, this.description, this.category, this.baselineFn);
}

final List<TestCase> testRegistry = [];

void registerTest(String id, String desc, String cat, String Function() fn) {
  testRegistry.add(TestCase(id, desc, cat, fn));
}
