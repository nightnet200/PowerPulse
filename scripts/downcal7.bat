@ECHO OFF

REM Apagar PCs incluidos en el archivo nombrado por fecha

REM Diego Roibás Tella
REM Gerencia Territorial del Catastro en Lugo
REM 31 de marzo de 2023
REM v.1.0
REM 09 de noviembre de 2026
REM v.2.0

SETLOCAL EnableExtensions EnableDelayedExpansion
TITLE APAGADO PROGRAMADO EQUIPOS LAN - REGS7
COLOR 0B

REM ==================================================
REM APAGADO PROGRAMADO DE EQUIPOS LAN
REM CALENDARIO REGS7
REM ==================================================

REM Obtener fecha en formato AA-MM-DD
SET "ANIO=%DATE:~6,4%"
SET "MES=%DATE:~3,2%"
SET "DIA=%DATE:~0,2%"
SET "ANIO2=%ANIO:~2,2%"
SET "FECHA=%ANIO2%-%MES%-%DIA%"

REM Directorios
SET "DIR_REGS=C:\ShutPCs\Calendario\regs7"
SET "DIR_LOGS=C:\ShutPCs\Calendario\logs7"

SET "FICHERO=%DIR_REGS%\%FECHA%.txt"
SET "LOG=%DIR_LOGS%\up_%FECHA%.log"
SET "INFO=%DIR_REGS%\%FECHA%.log"
SET "LOGINFO=%DIR_LOGS%\infoup_%FECHA%.log"

ECHO ==========================================
ECHO APAGADO PROGRAMADO DE EQUIPOS LAN
ECHO CALENDARIO REGS7
ECHO FECHA: %FECHA%
ECHO ==========================================
ECHO.

REM Comprobar calendario
IF NOT EXIST "%FICHERO%" (
    ECHO ERROR: No existe %FICHERO%
    PAUSE
    EXIT /B 1
)

REM Crear directorio de logs
IF NOT EXIST "%DIR_LOGS%" MKDIR "%DIR_LOGS%"

REM Iniciar log
ECHO APAGADO PROGRAMADO - %DATE% %TIME% > "%LOG%"
ECHO ========================================== >> "%LOG%"

REM Procesar equipos
FOR /F "usebackq tokens=* delims=" %%X IN ("%FICHERO%") DO (
    IF NOT "%%X"=="" (

        REM Extraer identificador de la IP
        SET "IP=%%X"
        SET "ID=!IP:~-3!"

        REM Construir nombre del equipo
        SET "EQUIPO=\\POLUG!ID!"

        ECHO.
        ECHO *** Shutdown !EQUIPO!
        ECHO *** Shutdown !EQUIPO! >> "%LOG%"

        REM Ejecutar apagado remoto
        SHUTDOWN /S /M !EQUIPO! /C "Apagado en 5 minutos. Guarde sus trabajos." /T 300

        SET "RESULTADO=!ERRORLEVEL!"

        IF !RESULTADO! EQU 0 (
            ECHO VALIDO: !EQUIPO!
            ECHO VALIDO: !EQUIPO! >> "%LOG%"
        ) ELSE (
            ECHO NO VALIDO: !EQUIPO! - Error !RESULTADO!
            ECHO NO VALIDO: !EQUIPO! - Error !RESULTADO! >> "%LOG%"
        )
    )
)

REM Copiar fichero de informacion si existe
IF EXIST "%INFO%" (
    COPY /Y "%INFO%" "%LOGINFO%" >NUL
)

ECHO.
ECHO ==========================================
ECHO PROCESO FINALIZADO
ECHO LOG: %LOG%
ECHO ==========================================
ECHO.

PAUSE
ENDLOCAL

