(function () {
  'use strict';

  const tg = window.Telegram && window.Telegram.WebApp;
  const root = document.getElementById('app');
  const navEl = document.getElementById('nav');
  const S = {
    cfg: { receipt_required: false, support: '', eta: '', shop_name: 'UC Shop' },
    user: null,
  };
  let pollTimer = null;
  let mainAction = null;
  let backAction = null;
  let navToken = 0; // защита от «позднего» ответа после перехода на другой экран

  // ───────── графика ─────────

  const EMBLEM =
    '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="14" fill="#171720"/>' +
    '<circle cx="24" cy="24" r="16" fill="url(#g-rim)"/><circle cx="24" cy="24" r="12.6" fill="url(#g-gold)"/>' +
    '<text x="24" y="28.6" text-anchor="middle" font-size="12" font-weight="900" fill="#7a3d00" font-family="Arial,sans-serif">UC</text></svg>';

  const ICONS = {
    shop: '<svg viewBox="0 0 24 24"><path d="M6 8h12l-1 11H7L6 8z"/><path d="M9 8a3 3 0 0 1 6 0"/></svg>',
    orders: '<svg viewBox="0 0 24 24"><path d="M7 4h10v16l-2.5-1.5L12 20l-2.5-1.5L7 20V4z"/><path d="M10 9h4M10 13h4"/></svg>',
    help: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1.9-1.1 1.7"/><circle cx="12" cy="17" r=".7" fill="currentColor"/></svg>',
  };

  // Золотые монеты: чем больше пакет, тем больше монет в «веере».
  function coinArt(uc) {
    const n = uc < 120 ? 1 : uc < 400 ? 2 : uc < 1000 ? 3 : uc < 3000 ? 4 : 5;
    const sc = n >= 4 ? 0.82 : 1;
    let g = '';
    for (let i = 0; i < n; i++) {
      const t = n === 1 ? 0.5 : i / (n - 1);
      const x = n === 1 ? 50 : 26 + t * 48;
      const y = n === 1 ? 38 : 46 - t * 14;
      const top = i === n - 1;
      g +=
        '<g transform="translate(' + x.toFixed(1) + ' ' + y.toFixed(1) + ') scale(' + sc + ')">' +
        '<circle cy="2.5" r="19" fill="rgba(0,0,0,.35)"/>' +
        '<circle r="19" fill="url(#g-rim)"/>' +
        '<circle r="15.5" fill="url(#g-gold)"/>' +
        '<circle r="15.5" fill="none" stroke="rgba(110,50,0,.4)" stroke-width="1"/>' +
        (top
          ? '<text y="5" text-anchor="middle" font-size="13" font-weight="900" fill="#7a3d00" font-family="Arial,sans-serif">UC</text>'
          : '<circle r="7" fill="none" stroke="rgba(110,50,0,.3)" stroke-width="1.2"/>') +
        '<path d="M-11 -5A12.5 12.5 0 0 1 3 -12.5" fill="none" stroke="rgba(255,255,255,.65)" stroke-width="2.4" stroke-linecap="round"/>' +
        '</g>';
    }
    return '<svg viewBox="0 0 100 72" aria-hidden="true">' + g + '</svg>';
  }

  // ───────── утилиты ─────────

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v; // только наши собственные строки (SVG), не данные пользователей
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
  function tap() {
    try { tg.HapticFeedback.impactOccurred('light'); } catch (_) { /* не поддерживается */ }
  }

  function toast(message) {
    const el = h('div', { class: 'toast' }, message);
    document.body.append(el);
    setTimeout(() => el.remove(), 3500);
  }

  function setMain(text, fn) {
    mainAction = fn || null;
    if (!text) { tg.MainButton.hide(); return; }
    try {
      tg.MainButton.setParams({ text: text, color: '#ffa31a', text_color: '#1b1000' });
    } catch (_) {
      tg.MainButton.setText(text);
    }
    tg.MainButton.show();
  }

  function setBack(fn) {
    backAction = fn || null;
    if (fn) tg.BackButton.show(); else tg.BackButton.hide();
  }

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function openPay(url) {
    if (url) tg.openLink(url);
  }

  function openSupport() {
    if (S.cfg.support) tg.openTelegramLink('https://t.me/' + S.cfg.support);
  }

  function pctOff(p) {
    return p.old_price && p.old_price > p.price ? Math.round((1 - p.price / p.old_price) * 100) : 0;
  }

  // ───────── каркас страницы ─────────

  function header() {
    const name = (S.user && S.user.first_name) || '';
    return h('header', { class: 'top' },
      h('div', { class: 'logo', html: EMBLEM }),
      h('div', { class: 'top-text' },
        h('div', { class: 'top-title' }, S.cfg.shop_name),
        h('div', { class: 'top-sub' }, 'Пополнение PUBG Mobile по ID')),
      h('button', { class: 'avatar', 'aria-label': 'Мои заказы', onclick: () => { tap(); showOrders(); } },
        (name[0] || 'U').toUpperCase()));
  }

  function subHeader(title) {
    return h('header', { class: 'sub' },
      h('button', { class: 'back', 'aria-label': 'Назад', onclick: () => { tap(); if (backAction) backAction(); } }, '‹'),
      h('div', { class: 'sub-title' }, title));
  }

  function renderNav(active) {
    if (!active) { navEl.hidden = true; return; }
    const items = [['shop', 'Магазин', showShop], ['orders', 'Заказы', showOrders], ['help', 'Помощь', showHelp]];
    navEl.replaceChildren(...items.map(([key, label, fn]) =>
      h('button', { class: 'nav-item' + (key === active ? ' active' : ''), onclick: () => { if (key !== active) { tap(); fn(); } } },
        h('span', { html: ICONS[key] }), label)));
    navEl.hidden = false;
  }

  // active — вкладка нижнего меню; title — для вложенных экранов (с кнопкой «назад»)
  function frame(active, nodes, title) {
    stopPoll();
    root.replaceChildren(title ? subHeader(title) : header(), ...nodes.flat().filter(Boolean));
    document.body.classList.toggle('has-nav', !!active);
    renderNav(active);
    window.scrollTo(0, 0);
  }

  function notice() {
    return h('div', { class: 'notice' },
      '⚡ UC зачисляются на указанный ID автоматически: ' + (S.cfg.eta || 'в течение нескольких минут') + '.');
  }

  function footer() {
    if (!S.cfg.support) return null;
    return h('p', { class: 'center muted small', style: 'margin:18px 16px 0' }, 'Вопросы? ',
      h('a', { href: '#', onclick: (e) => { e.preventDefault(); openSupport(); } }, '@' + S.cfg.support));
  }

  function errorBox(message, retry) {
    return h('div', { class: 'empty' },
      h('p', { style: 'margin-bottom:14px' }, message),
      h('button', { class: 'btn', onclick: retry }, 'Повторить'));
  }

  // ───────── магазин ─────────

  let heroEl = null;
  function hero() {
    if (!heroEl) {
      const video = h('video', {
        class: 'hero-video', src: 'img/hero.mp4', poster: 'img/hero.jpg',
        autoplay: true, loop: true, playsinline: true, preload: 'auto', 'aria-hidden': 'true',
      });
      video.muted = true; // у созданного скриптом элемента атрибут muted не включает беззвучный режим
      video.defaultMuted = true;
      heroEl = h('section', { class: 'hero glass' },
        h('div', { class: 'hero-media' }, video),
        h('div', { class: 'hero-bar' },
          h('div', null,
            h('div', { class: 'hero-title' }, 'Пополнение UC'),
            h('div', { class: 'hero-sub' }, 'PUBG Mobile · по Player ID')),
          h('button', {
            class: 'hero-btn',
            onclick: () => { tap(); const el = document.getElementById('packs') || document.getElementById('packs-wait'); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
          }, 'Пополнить')));
    }
    const v = heroEl.querySelector('video');
    setTimeout(() => {
      try { const r = v.play(); if (r && r.catch) r.catch(() => {}); } catch (_) { /* без автозапуска останется постер */ }
    }, 50);
    return heroEl;
  }

  function packCard(p) {
    const off = pctOff(p);
    return h('button', { class: 'pack glass', onclick: () => { tap(); showCheckout(p); } },
      off ? h('span', { class: 'pack-badge' }, '−' + off + '%') : null,
      h('span', { class: 'pack-art', html: coinArt(p.uc) }),
      h('span', { class: 'pack-uc' }, p.uc.toLocaleString('ru-RU'), h('small', null, 'UC')),
      h('span', { class: 'pack-old' }, off ? p.old_price_text : ''),
      h('span', { class: 'pack-price' }, p.price_text));
  }

  async function showShop() {
    const my = ++navToken;
    setMain(null); setBack(null);
    const skeleton = h('div', { class: 'packs', id: 'packs-wait' }, [1, 2, 3, 4, 5, 6].map(() => h('div', { class: 'skel' })));
    frame('shop', [hero(), notice(), h('div', { class: 'sec' }, 'Купить UC по ID'), skeleton]);
    let products;
    try {
      products = await api('/api/products');
    } catch (e) {
      if (my !== navToken) return;
      return frame('shop', [hero(), errorBox(e.message, showShop)]);
    }
    if (my !== navToken) return;
    if (!products.length) {
      return frame('shop', [hero(), h('div', { class: 'empty muted' }, 'Пакеты скоро появятся.')]);
    }
    frame('shop', [
      hero(), notice(),
      h('div', { class: 'sec' }, 'Купить UC по ID'),
      h('div', { class: 'packs', id: 'packs' }, products.map(packCard)),
      footer(),
    ]);
  }

  // ───────── оформление ─────────

  function showCheckout(p) {
    ++navToken;
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

    frame(null, [
      h('div', { class: 'sum-card glass' },
        h('div', { class: 'sum-art', html: coinArt(p.uc) }),
        h('div', null,
          h('div', { class: 'sum-uc' }, p.uc.toLocaleString('ru-RU') + ' UC'),
          h('div', { class: 'muted small' }, 'PUBG Mobile'),
          h('div', { class: 'sum-price' }, p.price_text))),
      h('div', { class: 'panel glass' },
        h('label', { class: 'field' },
          h('span', { class: 'label' }, 'Player ID'), pid,
          h('span', { class: 'hint-row' },
            h('span', { class: 'small muted' }, 'ID персонажа, не ник'),
            h('button', { class: 'link', onclick: () => { tap(); showHelp(); } }, 'Где найти ID?'))),
        email && h('label', { class: 'field' }, h('span', { class: 'label' }, 'Email для чека'), email)),
      h('div', { class: 'panel glass' }, h('div', { class: 'total' }, h('span', null, 'К оплате'), h('span', null, p.price_text))),
      h('p', { class: 'note' }, 'Оплата на защищённой странице ЮKassa. Пароль от игры не нужен.'),
    ], 'Оформление');
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

  function tracker(status) {
    const idx = { pending: 0, paid: 1, delivered: 3 }[status];
    if (idx === undefined) return null;
    return h('div', { class: 'track glass' }, ['Оплата', 'Начисление', 'Готово'].map((label, i) =>
      h('div', { class: 'step' + (i < idx ? ' done' : i === idx ? ' now' : '') },
        h('span', { class: 'dot' }, i < idx ? '✓' : String(i + 1)),
        h('span', null, label))));
  }

  function showOrder(order, autoOpen) {
    ++navToken;
    function draw(o) {
      const view = STATUS_VIEW[o.status] || ['•', o.status_text, ''];
      frame(null, [
        h('div', { class: 'state' },
          h('div', { class: 'state-ico' }, view[0]),
          h('h2', null, view[1]),
          h('p', { class: 'muted' }, view[2])),
        tracker(o.status),
        h('div', { class: 'details glass' },
          h('div', { class: 'row' }, h('span', null, 'Заказ'), h('span', null, '#' + o.short)),
          h('div', { class: 'row' }, h('span', null, 'Пакет'), h('span', null, o.uc.toLocaleString('ru-RU') + ' UC')),
          h('div', { class: 'row' }, h('span', null, 'Сумма'), h('span', null, o.price_text)),
          h('div', { class: 'row' }, h('span', null, 'Player ID'), h('span', null, o.player_id))),
        h('div', { class: 'actions' },
          o.status === 'pending' && o.payment_url && h('button', { class: 'btn', onclick: () => openPay(o.payment_url) }, 'Перейти к оплате'),
          h('button', { class: 'btn ghost', onclick: showOrders }, 'Мои заказы'),
          h('button', { class: 'btn ghost', onclick: showShop }, 'В магазин')),
        footer(),
      ], 'Заказ #' + o.short);
      setBack(showShop); setMain(null);
      if (FINAL.indexOf(o.status) === -1) startPoll(o);
    }
    function startPoll(o) {
      pollTimer = setInterval(async () => {
        try {
          const fresh = await api('/api/orders/' + o.id);
          if (fresh.status !== o.status) {
            if (fresh.status === 'delivered') haptic('success');
            draw(fresh);
          }
        } catch (_) { /* повторим на следующем тике */ }
      }, 3000);
    }
    draw(order);
    if (autoOpen && order.payment_url) openPay(order.payment_url);
  }

  // ───────── список заказов ─────────

  async function showOrders() {
    const my = ++navToken;
    setMain(null); setBack(null);
    frame('orders', [h('div', { class: 'sec' }, 'Мои заказы'), h('div', { class: 'empty muted' }, 'Загрузка…')]);
    let list;
    try {
      list = await api('/api/orders');
    } catch (e) {
      if (my !== navToken) return;
      return frame('orders', [errorBox(e.message, showOrders)]);
    }
    if (my !== navToken) return;
    if (!list.length) {
      return frame('orders', [
        h('div', { class: 'sec' }, 'Мои заказы'),
        h('div', { class: 'empty muted' }, 'Заказов пока нет.'),
        h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: showShop }, 'Купить UC')),
      ]);
    }
    frame('orders', [
      h('div', { class: 'sec' }, 'Мои заказы'),
      h('div', { class: 'orders' }, list.map((o) =>
        h('button', { class: 'order glass st-' + o.status, onclick: () => { tap(); showOrder(o, false); } },
          h('div', { class: 'order-art', html: coinArt(o.uc) }),
          h('div', { class: 'order-main' },
            h('div', { class: 'order-title' }, o.uc.toLocaleString('ru-RU') + ' UC · ' + o.price_text),
            h('div', { class: 'small muted' }, '#' + o.short + ' · ' +
              new Date(o.created_at).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })),
            h('span', { class: 'badge' }, o.status_text))))),
      footer(),
    ]);
  }

  // ───────── помощь ─────────

  function showHelp() {
    ++navToken;
    setMain(null); setBack(null);
    const faq = [
      ['Сколько ждать UC?', 'Обычно ' + (S.cfg.eta || 'несколько минут') + '. Статус заказа обновляется в разделе «Заказы», а когда UC будут начислены, бот пришлёт сообщение.'],
      ['Мне нужен пароль от аккаунта?', 'Нет. Для пополнения нужен только Player ID. Никому не сообщайте пароль и коды из SMS.'],
      ['Можно ли вернуть деньги?', 'Если заказ оплачен, но UC ещё не начислены, напишите в поддержку. После начисления UC вернуть нельзя, поэтому проверяйте Player ID перед оплатой.'],
      ['Что делать, если UC не пришли?', 'Подождите указанное время, затем напишите в поддержку и укажите номер заказа (он есть в разделе «Заказы»).'],
    ];
    frame('help', [
      h('div', { class: 'sec' }, 'Как найти Player ID'),
      h('div', { class: 'panel glass', style: 'margin-top:0' },
        h('ol', { class: 'steps' },
          h('li', null, 'Откройте PUBG Mobile.'),
          h('li', null, 'Нажмите на свой аватар в левом верхнем углу.'),
          h('li', null, 'Под ником указан ID персонажа: 8–12 цифр.'),
          h('li', null, 'Скопируйте его и вставьте в поле при оформлении.'))),
      h('div', { class: 'sec' }, 'Частые вопросы'),
      faq.map(([q, a]) => h('details', { class: 'faq glass' }, h('summary', null, q), h('p', null, a))),
      S.cfg.support && h('div', { class: 'actions', style: 'margin-top:16px' },
        h('button', { class: 'btn', onclick: openSupport }, 'Написать в поддержку')),
    ]);
  }

  // ───────── запуск ─────────

  (async function init() {
    if (!tg || !tg.initData) {
      root.append(h('div', { class: 'empty' },
        h('h2', { style: 'margin-bottom:8px' }, 'Откройте через Telegram'),
        h('p', { class: 'muted' }, 'Магазин работает как мини-приложение внутри Telegram-бота.')));
      return;
    }
    tg.ready();
    tg.expand();
    try { tg.disableVerticalSwipes(); } catch (_) { /* старые клиенты */ }
    try { tg.setHeaderColor('#09090e'); tg.setBackgroundColor('#09090e'); tg.setBottomBarColor('#09090e'); } catch (_) { /* старые клиенты */ }
    S.user = (tg.initDataUnsafe && tg.initDataUnsafe.user) || null;
    tg.MainButton.onClick(() => mainAction && mainAction());
    tg.BackButton.onClick(() => backAction && backAction());
    try { S.cfg = Object.assign(S.cfg, await api('/api/config')); } catch (_) { /* значения по умолчанию */ }
    showShop();
  })();
})();
