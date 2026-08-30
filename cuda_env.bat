@echo off
set "NVIDIA_ROOT=%~dp0..\AUTO_VIDEO_CUTTER_AI_GUI_3.1\.venv\Lib\site-packages\nvidia"
call :add "%NVIDIA_ROOT%\cublas\bin"
call :add "%NVIDIA_ROOT%\cudnn\bin"
call :add "%NVIDIA_ROOT%\cuda_runtime\bin"
call :add "%NVIDIA_ROOT%\nvjitlink\bin"
call :add "%NVIDIA_ROOT%\cusparse\bin"
if defined CUDA_PATH call :add "%CUDA_PATH%\bin"
goto :eof
:add
if exist "%~1" set "PATH=%~1;%PATH%"
goto :eof
