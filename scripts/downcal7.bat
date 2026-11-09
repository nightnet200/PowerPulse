
@ECHO OFF
SETLOCAL EnableExtensions EnableDelayedExpansion
TITLE APAGADO EQUIPOS LAN - REGS7
COLOR 0B

REM ==================================================
REM APAGADO PROGRAMADO DE EQUIPOS LAN
REM CALENDARIO REGS7
REM ==================================================

REM Obtener fecha en formato AAAA-MM-DD
FOR /F %%I IN ('POWERSHELL -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') DO SET "FECHA=%%I"

REM Directorios
SET "DIR_REGS=C:\ShutPCs\Calendario\regs7"
SET "DIR_LOGS=C:\ShutPCs\Calendario\logs7"

SET "FICHERO=%DIR_REGS%\%FECHA%.txt"
SET "LOG=%DIR_LOGS%\up_%FECHA%.log"

ECHO ==========================================
ECHO APAGADO PROGRAMADO DE EQUIPOS LAN
ECHO CALENDARIO REGS7
ECHO FECHA: %FECHA%
ECHO ==========================================
ECHO.

REM Comprobar calendario
IF NOT EXIST "%FICHERO%" (
    ECHO ERROR: No existe el fichero:
    ECHO %FICHERO%
    PAUSE
    EXIT /B 1
)

REM Crear directorio de logs
IF NOT EXIST "%DIR_LOGS%" MKDIR "%DIR_LOGS%"

REM Inicializar registro
ECHO APAGADO LAN - %DATE% %TIME% > "%LOG%"
ECHO ========================================== >> "%LOG%"

REM Contadores
SET /A TOTAL=0
SET /A CORRECTOS=0
SET /A ERRORES=0

REM Procesar calendario
FOR /F "usebackq tokens=* delims=" %%X IN ("%FICHERO%") DO (

    SET "IP=%%X"

    IF NOT "!IP!"=="" (

        REM Extraer identificador
        SET "ID=!IP:~-3!"
        SET "EQUIPO=\\POLUG!ID!"

        SET /A TOTAL+=1

        ECHO.
        ECHO ==========================================
        ECHO IP: !IP!
        ECHO EQUIPO: !EQUIPO!
        ECHO Ejecutando apagado...

        ECHO ------------------------------------------ >> "%LOG%"
        ECHO IP: !IP! >> "%LOG%"
        ECHO EQUIPO: !EQUIPO! >> "%LOG%"

        REM Ejecutar comando de apagado
        SHUTDOWN /S /M !EQUIPO! /C "Cerrando" >> "%LOG%" 2>&1

        SET "RESULTADO=!ERRORLEVEL!"

        IF !RESULTADO! EQU 0 (
            ECHO VALIDO: !EQUIPO!
            ECHO VALIDO: !EQUIPO! >> "%LOG%"
            SET /A CORRECTOS+=1
        ) ELSE (
            ECHO NO VALIDO: !EQUIPO! - ERROR !RESULTADO!
            ECHO NO VALIDO: !EQUIPO! - ERROR !RESULTADO! >> "%LOG%"
            SET /A ERRORES+=1
        )
    )
)

REM Resumen
ECHO.
ECHO ==========================================
ECHO RESUMEN DEL PROCESO
ECHO ==========================================
ECHO Equipos procesados: !TOTAL!
ECHO Solicitudes aceptadas: !CORRECTOS!
ECHO Errores: !ERRORES!

ECHO. >> "%LOG%"
ECHO TOTAL: !TOTAL! >> "%LOG%"
ECHO SOLICITUDES ACEPTADAS: !CORRECTOS! >> "%LOG%"
ECHO ERRORES: !ERRORES! >> "%LOG%"

ECHO.
ECHO LOG: %LOG%
ECHO ==========================================

PAUSE
ENDLOCAL
