import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_hot_patcher_plugin/flutter_hot_patcher_plugin.dart';
import 'package:flutter_hot_patcher_plugin/flutter_hot_patcher_plugin_platform_interface.dart';
import 'package:flutter_hot_patcher_plugin/flutter_hot_patcher_plugin_method_channel.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';

class MockFlutterHotPatcherPluginPlatform
    with MockPlatformInterfaceMixin
    implements FlutterHotPatcherPluginPlatform {

  @override
  Future<String?> getPlatformVersion() => Future.value('42');
}

void main() {
  final FlutterHotPatcherPluginPlatform initialPlatform = FlutterHotPatcherPluginPlatform.instance;

  test('$MethodChannelFlutterHotPatcherPlugin is the default instance', () {
    expect(initialPlatform, isInstanceOf<MethodChannelFlutterHotPatcherPlugin>());
  });

  test('getPlatformVersion', () async {
    FlutterHotPatcherPlugin flutterHotPatcherPlugin = FlutterHotPatcherPlugin();
    MockFlutterHotPatcherPluginPlatform fakePlatform = MockFlutterHotPatcherPluginPlatform();
    FlutterHotPatcherPluginPlatform.instance = fakePlatform;

    expect(await flutterHotPatcherPlugin.getPlatformVersion(), '42');
  });
}
