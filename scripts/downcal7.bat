@ECHO OFF

REM Apagar PCs incluidos en el archivo nombrado por fecha

REM Diego Roibás Tella
REM Gerencia Territorial del Catastro en Lugo
REM 31 de marzo de 2023
REM v.1.0
REM 09 de noviembre de 2026
REM v.2.0

REM Fijar variables temporales
SET anio=%date:~6,4%
SET mes=%date:~3,2%
SET dia=%date:~0,2%
echo %anio%-%mes%-%dia%
REM Bucle de apagado
timeout /t 1
for /F "delims=" %%x in (C:\ShutPCs\Calendario\regs7\%anio%-%mes%-%dia%.txt) do (
	echo ***Shutdown %%x
	shutdown /s /m %%x /c "Apagado en 5 minutos. Guarde sus trabajos." /t 300
) 
timeout /t 1
COPY C:\ShutPCs\Calendario\regs7\%anio%-%mes%-%dia%.txt C:\ShutPCs\Calendario\logs7\up_%anio%-%mes%-%dia%.log
COPY C:\ShutPCs\Calendario\regs7\%anio%-%mes%-%dia%.log C:\ShutPCs\Calendario\logs7\infoup_%anio%-%mes%-%dia%.log