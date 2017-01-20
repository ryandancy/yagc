@echo off
set PATH=%PATH%;%~dp0
:repl
  set /p command="%CD% $ "
  call %command%
  echo.
goto repl
