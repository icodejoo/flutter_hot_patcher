import 'package:flutter/material.dart';

/// 被 OTA 补丁替换的函数。
@pragma('vm:never-inline')
String buildLabel() => 'OTA_PATCHED_V2';

/// 把结果写入容器内文件，便于用 devicectl 读回做机器判定，
/// 不依赖看屏幕或抓日志。该函数在 baseline 与补丁版中完全相同。
void _writeResult(String label) {
  // 本引擎把 Dart 跑在 Simulator 下，dart:io 文件操作会抛
  // "Not supported on simulated architectures"，故改用 debugPrint，
  // 经引擎日志通道输出，可用 idevicesyslog 读回做机器判定。
  debugPrint('FHP_RESULT=$label');
}

void main() => runApp(const ValApp());

class ValApp extends StatelessWidget {
  const ValApp({super.key});

  @override
  Widget build(BuildContext context) {
    final label = buildLabel();
    _writeResult(label);
    final patched = label != 'BASELINE_V1';
    return MaterialApp(
      home: Scaffold(
        backgroundColor: patched ? Colors.green.shade50 : Colors.orange.shade50,
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(label,
                  style: TextStyle(
                      fontSize: 30,
                      fontWeight: FontWeight.bold,
                      color: patched ? Colors.green.shade900 : Colors.orange.shade900)),
              const SizedBox(height: 12),
              Text(patched ? 'PATCH ACTIVE' : 'baseline',
                  style: const TextStyle(fontSize: 16)),
            ],
          ),
        ),
      ),
    );
  }
}
