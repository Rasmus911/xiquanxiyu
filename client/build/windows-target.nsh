!include "LogicLib.nsh"
!include "x64.nsh"

!macro customInit
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  System::Alloc 284
  Pop $0
  ${If} $0 == 0
    MessageBox MB_ICONSTOP "无法检查系统版本，安装已停止。"
    Abort
  ${EndIf}
  System::Call '*$0(i 284)'
  System::Call 'ntdll::RtlGetVersion(p r0)i.r1'
  System::Call '*$0(i, i.r2, i.r3, i.r4)'
  System::Free $0
  ${If} $1 != 0
    MessageBox MB_ICONSTOP "无法确认系统版本，安装已停止。"
    Abort
  ${EndIf}
  !if "${XQ_TARGET_FAMILY}" == "win7"
    ${If} $2 != 6
    ${OrIf} $3 != 1
    ${OrIf} $4 != 7601
      MessageBox MB_ICONSTOP "这是Windows 7 SP1安装包，请选择与本机系统对应的溪泉版本。"
      Abort
    ${EndIf}
  !else
    ${If} $2 != 10
    ${OrIf} $3 != 0
    ${OrIf} $4 < 10240
      MessageBox MB_ICONSTOP "此安装包需要Windows 10或Windows 11。Windows 7请使用专用版本。"
      Abort
    ${EndIf}
    !if "${XQ_TARGET_FAMILY}" == "win11"
      ${If} $4 < 22000
      ${OrIfNot} ${RunningX64}
        MessageBox MB_ICONSTOP "这是Windows 11专用安装包，请选择本机对应的Windows 10版本。"
        Abort
      ${EndIf}
    !endif
  !endif
  !if "${XQ_TARGET_ARCH}" == "x64"
    ${IfNot} ${RunningX64}
      MessageBox MB_ICONSTOP "此安装包包含64位程序，本机请使用32位（x86）安装包。"
      Abort
    ${EndIf}
  !endif
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
!macroend
