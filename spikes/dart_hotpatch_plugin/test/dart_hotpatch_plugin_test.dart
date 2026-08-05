import 'package:flutter_test/flutter_test.dart';
import 'package:dart_hotpatch_plugin/dart_hotpatch_plugin.dart';
import 'package:dart_hotpatch_plugin/dart_hotpatch_plugin_platform_interface.dart';
import 'package:dart_hotpatch_plugin/dart_hotpatch_plugin_method_channel.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';

class MockDartHotpatchPluginPlatform
    with MockPlatformInterfaceMixin
    implements DartHotpatchPluginPlatform {

  @override
  Future<String?> getPlatformVersion() => Future.value('42');
}

void main() {
  final DartHotpatchPluginPlatform initialPlatform = DartHotpatchPluginPlatform.instance;

  test('$MethodChannelDartHotpatchPlugin is the default instance', () {
    expect(initialPlatform, isInstanceOf<MethodChannelDartHotpatchPlugin>());
  });

  test('getPlatformVersion', () async {
    DartHotpatchPlugin dartHotpatchPlugin = DartHotpatchPlugin();
    MockDartHotpatchPluginPlatform fakePlatform = MockDartHotpatchPluginPlatform();
    DartHotpatchPluginPlatform.instance = fakePlatform;

    expect(await dartHotpatchPlugin.getPlatformVersion(), '42');
  });
}
