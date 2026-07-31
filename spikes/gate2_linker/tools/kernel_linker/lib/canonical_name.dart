import 'package:kernel/ast.dart' as k;

/// Stable identifier for a Dart procedure across builds.
/// Format: `package:lib/file.dart::ClassName.methodName`
/// or       `package:lib/file.dart::topLevelFn`
/// Disambiguation suffix `@offset` is appended only when needed (overloads).
class FunctionId {
  final String libraryUri;
  final String? className;
  final String memberName;
  final int fileOffset;

  FunctionId({
    required this.libraryUri,
    this.className,
    required this.memberName,
    required this.fileOffset,
  });

  String get base {
    final cls = className != null ? '$className.' : '';
    return '$libraryUri::$cls$memberName';
  }

  @override
  String toString() => base;

  @override
  bool operator ==(Object other) =>
      other is FunctionId &&
      libraryUri == other.libraryUri &&
      className == other.className &&
      memberName == other.memberName;

  @override
  int get hashCode => Object.hash(libraryUri, className, memberName);
}

FunctionId functionIdForProcedure(k.Procedure proc) {
  final lib = proc.enclosingLibrary;
  final uri = lib.importUri.toString();
  final cls = proc.enclosingClass?.name;
  return FunctionId(
    libraryUri: uri,
    className: cls,
    memberName: proc.name.text,
    fileOffset: proc.fileOffset,
  );
}

bool isUserLibrary(k.Library lib) {
  final scheme = lib.importUri.scheme;
  return scheme != 'dart' && scheme != 'org-dartlang-sdk';
}

/// Extracts all procedures from user libraries in a component.
List<k.Procedure> extractUserProcedures(k.Component component) {
  final procs = <k.Procedure>[];
  for (final lib in component.libraries) {
    if (!isUserLibrary(lib)) continue;
    for (final klass in lib.classes) {
      procs.addAll(klass.procedures);
    }
    procs.addAll(lib.procedures);
  }
  return procs;
}
