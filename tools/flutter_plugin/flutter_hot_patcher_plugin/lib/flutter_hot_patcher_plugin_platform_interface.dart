import 'package:plugin_platform_interface/plugin_platform_interface.dart';

import 'flutter_hot_patcher_plugin_method_channel.dart';

abstract class FlutterHotPatcherPluginPlatform extends PlatformInterface {
  /// Constructs a FlutterHotPatcherPluginPlatform.
  FlutterHotPatcherPluginPlatform() : super(token: _token);

  static final Object _token = Object();

  static FlutterHotPatcherPluginPlatform _instance = MethodChannelFlutterHotPatcherPlugin();

  /// The default instance of [FlutterHotPatcherPluginPlatform] to use.
  ///
  /// Defaults to [MethodChannelFlutterHotPatcherPlugin].
  static FlutterHotPatcherPluginPlatform get instance => _instance;

  /// Platform-specific implementations should set this with their own
  /// platform-specific class that extends [FlutterHotPatcherPluginPlatform] when
  /// they register themselves.
  static set instance(FlutterHotPatcherPluginPlatform instance) {
    PlatformInterface.verifyToken(instance, _token);
    _instance = instance;
  }

  Future<String?> getPlatformVersion() {
    throw UnimplementedError('platformVersion() has not been implemented.');
  }
}
