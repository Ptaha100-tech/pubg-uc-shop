(function () {
  'use strict';

  const tg = window.Telegram && window.Telegram.WebApp;
  const root = document.getElementById('app');
  const S = { cfg: { receipt_required: false, support: '', eta: '' }, products: null };
  let pollTimer = null;
  let mainAction = null;
  let backAction = null;

  // ───────── утилиты ─────────

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key) || '';
      localStorage.setItem(key, value);
    } catch (_) { /* приватный режим */ }
    return '';
  }

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({}, opts, {
      headers: { 'Content-Type': 'application/json', Authorization: 'tma ' + tg.initData },
    }));
    let data = null;
    try { data = await res.json(); } catch (_) { /* пустой ответ */ }
    if (!res.ok) {
      const d = data && data.detail;
      throw new Error(typeof d === 'string' ? d : 'Проверьте введённые данные');
    }
    return data;
  }

  function haptic(kind) {
    try { tg.HapticFeedback.notificationOccurred(kind); } catch (_) { /* не поддерживается */ }
  }

  function toast(message) {
    const el = h('div', { class: 'toast' }, message);
    document.body.append(el);
    setTimeout(() => el.remove(), 3500);
  }

  function setMain(text, fn) {
    mainAction = fn || null;
    if (!text) { tg.MainButton.hide(); return; }
    tg.MainButton.setText(text);
    tg.MainButton.show();
  }

  function setBack(fn) {
    backAction = fn || null;
    if (fn) tg.BackButton.show(); else tg.BackButton.hide();
  }

  function mount(...nodes) {
    stopPoll();
    root.replaceChildren(...nodes.flat());
    window.scrollTo(0, 0);
  }

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function openPay(url) {
    if (url) tg.openLink(url);
  }

  function tabs(active) {
    return h('div', { class: 'tabs' },
      h('button', { class: 'tab' + (active === 'shop' ? ' active' : ''), onclick: showShop }, 'Купить UC'),
      h('button', { class: 'tab' + (active === 'orders' ? ' active' : ''), onclick: showOrders }, 'Мои заказы'),
    );
  }

  function supportFooter() {
    if (!S.cfg.support) return null;
    return h('p', { class: 'center muted small' }, 'Поддержка: ',
      h('a', { href: '#', onclick: (e) => { e.preventDefault(); tg.openTelegramLink('https://t.me/' + S.cfg.support); } }, '@' + S.cfg.support));
  }

  // ───────── витрина ─────────

  async function showShop() {
    setMain(null); setBack(null);
    mount(tabs('shop'), h('p', { class: 'center muted pad' }, 'Загрузка…'));
    try {
      S.products = await api('/api/products');
    } catch (e) {
      return mount(tabs('shop'), h('div', { class: 'pad center' },
        h('p', null, e.message),
        h('button', { class: 'btn', onclick: showShop }, 'Повторить')));
    }
    if (!S.products.length) {
      return mount(tabs('shop'), h('p', { class: 'center muted pad' }, 'Пакеты скоро появятся.'));
    }
    mount(
      tabs('shop'),
      h('div', { class: 'grid' }, S.products.map((p) =>
        h('button', { class: 'card', onclick: () => showCheckout(p) },
          h('div', { class: 'coin' }, 'UC'),
          h('div', { class: 'uc' }, p.uc.toLocaleString('ru-RU')),
          h('div', { class: 'price' }, p.price_text)))),
      h('p', { class: 'center muted small' }, 'Начисление: ' + (S.cfg.eta || 'в течение нескольких минут')),
      supportFooter(),
    );
  }

  // ───────── оформление ─────────

  function showCheckout(p) {
    const pid = h('input', {
      class: 'input', type: 'text', inputmode: 'numeric', autocomplete: 'off',
      maxlength: 12, placeholder: 'Например, 5123456789', value: store('pid'),
    });
    const email = S.cfg.receipt_required
      ? h('input', { class: 'input', type: 'email', autocomplete: 'email', placeholder: 'you@example.com', value: store('email') })
      : null;

    pid.addEventListener('input', () => {
      pid.value = pid.value.replace(/\D/g, '');
      pid.classList.remove('bad');
    });

    async function submit() {
      const id = pid.value.trim();
      if (!/^\d{8,12}$/.test(id)) {
        pid.classList.add('bad'); haptic('error');
        return toast('Player ID — это 8–12 цифр');
      }
      if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email.value.trim())) {
        email.classList.add('bad'); haptic('error');
        return toast('Введите корректный email для чека');
      }
      tg.showConfirm(
        'Начислить ' + p.uc + ' UC на Player ID ' + id + '?\nПосле начисления вернуть UC нельзя — проверьте ID.',
        async (ok) => {
          if (!ok) return;
          tg.MainButton.showProgress();
          try {
            const order = await api('/api/orders', {
              method: 'POST',
              body: JSON.stringify({ product_id: p.id, player_id: id, email: email ? email.value.trim() : null }),
            });
            store('pid', id);
            if (email) store('email', email.value.trim());
            tg.MainButton.hideProgress();
            showOrder(order, true);
          } catch (e) {
            tg.MainButton.hideProgress();
            haptic('error');
            tg.showAlert(e.message);
          }
        });
    }

    mount(
      h('div', { class: 'pad' }, h('h1', null, p.uc.toLocaleString('ru-RU') + ' UC'), h('p', { class: 'muted' }, 'PUBG Mobile')),
      h('div', { class: 'panel' },
        h('label', { class: 'field' },
          h('span', { class: 'label' }, 'Player ID'), pid,
          h('span', { class: 'label small', style: 'margin:6px 0 0' }, 'В игре: Профиль → ID персонажа')),
        email && h('label', { class: 'field' }, h('span', { class: 'label' }, 'Email для чека'), email)),
      h('div', { class: 'panel' }, h('div', { class: 'sum' }, h('span', null, 'К оплате'), h('span', null, p.price_text))),
      h('p', { class: 'center muted small pad' }, 'Оплата на защищённой странице ЮKassa: карта или СБП.'),
    );
    setBack(showShop);
    setMain('Оплатить ' + p.price_text, submit);
  }

  // ───────── статус заказа ─────────

  const STATUS_VIEW = {
    pending: ['⏳', 'Ожидаем оплату', 'Завершите оплату на странице ЮKassa. Статус здесь обновится сам.'],
    paid: ['💳', 'Оплата получена', 'Начисляем UC на ваш аккаунт.'],
    delivered: ['✅', 'UC начислены!', 'Заходите в игру. Приятной игры!'],
    canceled: ['✖️', 'Заказ отменён', 'Оплата не поступила. Можно оформить новый заказ.'],
    refunded: ['↩️', 'Возврат оформлен', 'Деньги вернутся на карту в течение нескольких дней.'],
  };
  const FINAL = ['delivered', 'canceled', 'refunded'];

  function showOrder(order, autoOpen) {
    setBack(showShop);
    function draw(o) {
      const [icon, title, text] = STATUS_VIEW[o.status] || ['•', o.status_text, ''];
      mount(
        h('div', { class: 'pad center' },
          h('div', { class: 'status-icon' }, icon),
          h('h2', null, title),
          h('p', { class: 'muted' }, text),
          h('p', { class: 'small muted' }, 'Заказ #' + o.short + ' · ' + o.uc + ' UC · ' + o.price_text + ' · ID ' + o.player_id)),
        h('div', { class: 'pad' },
          o.status === 'pending' && o.payment_url && h('button', { class: 'btn', onclick: () => openPay(o.payment_url) }, 'Перейти к оплате'),
          h('button', { class: 'btn ghost', onclick: showOrders }, 'Мои заказы'),
          h('button', { class: 'btn ghost', onclick: showShop }, 'В магазин')),
        supportFooter(),
      );
      setBack(showShop); setMain(null);
      if (FINAL.indexOf(o.status) !== -1) {
        stopPoll();
      } else if (!pollTimer) {
        startPoll(o);
      }
    }
    function startPoll(o) {
      pollTimer = setInterval(async () => {
        try {
          const fresh = await api('/api/orders/' + o.id);
          if (fresh.status !== o.status) {
            if (fresh.status === 'delivered') haptic('success');
            o = fresh; stopPoll(); draw(fresh);
          }
        } catch (_) { /* повторим на следующем тике */ }
      }, 3000);
    }
    draw(order);
    if (autoOpen && order.payment_url) openPay(order.payment_url);
  }

  // ───────── список заказов ─────────

  async function showOrders() {
    setMain(null); setBack(null);
    mount(tabs('orders'), h('p', { class: 'center muted pad' }, 'Загрузка…'));
    let list;
    try {
      list = await api('/api/orders');
    } catch (e) {
      return mount(tabs('orders'), h('div', { class: 'pad center' }, h('p', null, e.message),
        h('button', { class: 'btn', onclick: showOrders }, 'Повторить')));
    }
    if (!list.length) {
      return mount(tabs('orders'), h('p', { class: 'center muted pad' }, 'Заказов пока нет.'));
    }
    mount(
      tabs('orders'),
      h('div', { class: 'orders' }, list.map((o) =>
        h('button', { class: 'order', onclick: () => showOrder(o, false) },
          h('div', { class: 'row' },
            h('div', null,
              h('div', { class: 'title' }, o.uc.toLocaleString('ru-RU') + ' UC · ' + o.price_text),
              h('div', { class: 'small muted' }, '#' + o.short + ' · ' + new Date(o.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }))),
            h('div', { class: 'badge' }, o.status_text))))),
      supportFooter(),
    );
  }

  // ───────── запуск ─────────

  (async function init() {
    if (!tg || !tg.initData) {
      root.append(h('div', { class: 'pad center' },
        h('h2', null, 'Откройте через Telegram'),
        h('p', { class: 'muted' }, 'Магазин работает как мини-приложение внутри Telegram-бота.')));
      return;
    }
    tg.ready();
    tg.expand();
    try { tg.disableVerticalSwipes(); } catch (_) { /* старые клиенты */ }
    tg.MainButton.onClick(() => mainAction && mainAction());
    tg.BackButton.onClick(() => backAction && backAction());
    try { S.cfg = await api('/api/config'); } catch (_) { /* значения по умолчанию */ }
    showShop();
  })();
})();
