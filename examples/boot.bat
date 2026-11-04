@echo off
set BOT_URL=http://YOUR_VPS_IP:6666/v1/create
set API_SECRET=long_random_secret_here

curl -s -X POST "%BOT_URL%" ^
  -H "Authorization: Bearer %API_SECRET%" ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"PC boot\",\"body\":\"%COMPUTERNAME% started\"}"
