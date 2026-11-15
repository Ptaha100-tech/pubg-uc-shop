#!/usr/bin/env bash
# Интерактивно создаёт файл .env (без правки в редакторе).
# Запуск из папки проекта:  bash deploy/setup-env.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  read -rp ".env уже существует. Перезаписать? (yes/no): " ans
  [ "$ans" = "yes" ] || { echo "Отменено, файл не тронут."; exit 1; }
fi

# ask ИМЯ "Вопрос" [значение_по_умолчанию] [регулярное_выражение_проверки]
ask() {
  local var="$1" prompt="$2" def="${3-}" re="${4-}" val
  while true; do
    if [ -n "$def" ]; then
      read -rp "$prompt [$def]: " val
      val="${val:-$def}"
    else
      read -rp "$prompt: " val
    fi
    val="${val//[[:space:]]/}"
    if [ -z "$val" ]; then
      echo "  Значение не может быть пустым."
    elif [ -n "$re" ] && ! [[ "$val" =~ $re ]]; then
      echo "  Похоже на ошибку в формате, попробуйте ещё раз."
    else
      break
    fi
  done
  printf -v "$var" '%s' "$val"
}

echo "Отвечайте на вопросы. Значения можно вставлять из буфера обмена."
echo

ask BOT_TOKEN "1/7 Токен бота (от @BotFather)" "" '^[0-9]+:[A-Za-z0-9_-]{30,}$'
ask BOT_USERNAME "2/7 Username бота (без @)" "" '^@?[A-Za-z0-9_]{5,}$'
BOT_USERNAME="${BOT_USERNAME#@}"
ask ADMIN_IDS "3/7 Ваш Telegram ID (число от @userinfobot; несколько через запятую)" "" '^[0-9]+(,[0-9]+)*$'
ask SUPPORT_USERNAME "4/7 Username для поддержки клиентов (без @)" "" '^@?[A-Za-z0-9_]{5,}$'
SUPPORT_USERNAME="${SUPPORT_USERNAME#@}"
ask PUBLIC_URL "5/7 Адрес магазина" "https://nevechen-shop.ru" '^https://[^/]+$'
echo "ЮKassa: если магазина там ещё нет, в двух следующих вопросах введите слово test."
echo "Витрина и бот заработают, а оплата начнёт работать после замены на настоящие данные."
ask YOOKASSA_SHOP_ID "6/7 shopId ЮKassa"
ask YOOKASSA_SECRET_KEY "7/7 Секретный ключ ЮKassa"

WEBHOOK_SECRET="$(openssl rand -hex 24)"
POSTGRES_PASSWORD="$(openssl rand -hex 16)"

umask 077
cat > .env <<EOF
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

BOT_TOKEN=${BOT_TOKEN}
BOT_USERNAME=${BOT_USERNAME}
PUBLIC_URL=${PUBLIC_URL}
WEBHOOK_SECRET=${WEBHOOK_SECRET}
ADMIN_IDS=${ADMIN_IDS}
SUPPORT_USERNAME=${SUPPORT_USERNAME}

YOOKASSA_SHOP_ID=${YOOKASSA_SHOP_ID}
YOOKASSA_SECRET_KEY=${YOOKASSA_SECRET_KEY}

RECEIPT_ENABLED=false
RECEIPT_VAT_CODE=1
RECEIPT_PAYMENT_SUBJECT=service
RECEIPT_PAYMENT_MODE=full_payment

SUPPLIER=manual
DELIVERY_ETA_TEXT=обычно до 15 минут
ORDER_TTL_MINUTES=70
MAX_PENDING_ORDERS=5
TIMEZONE=Europe/Moscow
EOF

echo
echo "Готово: файл .env создан (читать его может только root)."
echo "Дальше запустите:  docker compose up -d --build"
