library;

// A second, DIFFERENT patch — demonstrates that after install.sh has run
// ONCE, shipping a follow-up fix is just "compile this file, push one small
// bytecode file, restart" — no reinstall of the base app.
//
// 第二个、不一样的补丁——演示 install.sh 只跑一次之后，发一个后续修复只是
// "编译这个文件、推一个小字节码文件、重启"——不用重装基础 app。
@pragma('dyn-module:entry-point')
String fPatched() => 'PATCHED-V2-FOLLOWUP-FIX';
