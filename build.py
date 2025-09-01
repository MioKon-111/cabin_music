import os
import shutil
import PyInstaller.__main__

def build_exe():
    # 清理旧构建
    if os.path.exists("build"):
        shutil.rmtree("build")
    if os.path.exists("dist"):
        shutil.rmtree("dist")


    pyuipc_binary_path = r'F:\py386\lib\site-packages\pyuipc.cp38-win32.pyd'

    if not os.path.exists(pyuipc_binary_path):
        print("ERROR: 找不到 pyuipc .pyd 文件，请检查路径！")
        return


    # 构建 PyInstaller 参数
    pyinstaller_args = [
        'app_ui.py',  # 主程序入口
        '--onefile',  # 打包成单文件
        '--windowed',  # 无控制台窗口
        '--name=CabinVoice',
        '--ico=assets/airline_logo.ico',
        f'--add-binary={pyuipc_binary_path};.',  # 添加 pyuipc
        '--clean',
        '--noconfirm',
        '--add-data=assets{}assets'.format(os.pathsep),
        '--add-data=sounds{}sounds'.format(os.pathsep),
        '--hidden-import=pyuipc',
        '--hidden-import=pygame',
        '--hidden-import=PyQt5',
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui',
        '--hidden-import=PyQt5.QtWidgets',
    ]

    PyInstaller.__main__.run(pyinstaller_args)

    print("\n✅ 打包完成！EXE 位于 dist 目录")
    print("📦 请一并打包：dist/CabinVoice.exe + assets 文件夹 + sounds 文件夹")

if __name__ == "__main__":
    build_exe()
