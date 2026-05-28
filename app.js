/* ============================================
   PUNK PLANET — 主交互逻辑
   ============================================ */

// 把 PUNK_DATA 转换为地球可消费的点数据
const points = Object.entries(PUNK_DATA).map(([code, c]) => ({
  code,
  lat: c.lat,
  lng: c.lng,
  name: c.name,
  flag: c.flag,
  bandsCount: c.bands.length,
  songsCount: c.bands.reduce((sum, b) => sum + b.songs.length, 0),
  size: 0.6 + Math.min(c.bands.length, 8) * 0.05,
  color: getCountryColor(code)
}));

function getCountryColor(code) {
  // 不同区域不同色调
  const palette = {
    US: "#ff2d8a", CA: "#ff6b1c", MX: "#fff04d", BR: "#b9ff3a", AR: "#00f0ff",
    GB: "#ff1f3d", DE: "#ff2d8a", FR: "#fff04d", IT: "#b9ff3a", SE: "#00f0ff", RU: "#ff6b1c",
    CN: "#ff1f3d", JP: "#ff2d8a", KR: "#fff04d", PH: "#b9ff3a", ID: "#00f0ff",
    AU: "#ff6b1c"
  };
  return palette[code] || "#ff2d8a";
}

// ---------- 初始化 Globe.gl ----------
const globeEl = document.getElementById("globe");

const world = Globe()
  .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-night.jpg")
  .bumpImageUrl("https://unpkg.com/three-globe/example/img/earth-topology.png")
  .backgroundColor("rgba(0,0,0,0)")
  .showAtmosphere(true)
  .atmosphereColor("#ff2d8a")
  .atmosphereAltitude(0.18)
  // 标记点
  .pointsData(points)
  .pointAltitude(d => 0.04 + d.size * 0.04)
  .pointColor(d => d.color)
  .pointRadius(d => d.size)
  .pointResolution(16)
  .pointsMerge(false)
  .pointsTransitionDuration(700)
  // 文字标签（国旗 emoji）
  .labelsData(points)
  .labelLat(d => d.lat)
  .labelLng(d => d.lng)
  .labelText(d => d.flag)
  .labelSize(d => 0.9 + d.size * 0.4)
  .labelDotRadius(0)
  .labelColor(() => "rgba(255,255,255,0.9)")
  .labelResolution(2)
  .labelAltitude(d => 0.06 + d.size * 0.04)
  // 光环
  .ringsData(points)
  .ringLat(d => d.lat)
  .ringLng(d => d.lng)
  .ringColor(d => t => `rgba(${hexToRgb(d.color)}, ${1 - t})`)
  .ringMaxRadius(d => 3 + d.size * 4)
  .ringPropagationSpeed(2.5)
  .ringRepeatPeriod(2200)
  // 交互 tooltip
  .pointLabel(d => `
    <div style="
      background: #f4ecd8; color: #1a1a1a; padding: 10px 14px;
      border: 2px solid #1a1a1a; box-shadow: 4px 4px 0 #ff2d8a;
      font-family: 'Noto Sans SC', sans-serif; font-size: 13px; line-height: 1.5;">
      <div style="font-family:'Bungee',sans-serif; font-size:16px;">
        ${d.flag} ${d.name}
      </div>
      <div style="font-size:11px; color:rgba(0,0,0,0.6); margin-top:2px;">
        🎸 ${d.bandsCount} 支乐队 · 🎵 ${d.songsCount} 首推荐
      </div>
      <div style="font-size:10px; color:#ff2d8a; margin-top:6px; letter-spacing:1.5px;">
        ★ CLICK TO EXPLORE ★
      </div>
    </div>
  `)
  .onPointClick(d => {
    showCountryDetail(d.code);
    // 飞过去
    world.pointOfView({ lat: d.lat, lng: d.lng, altitude: 1.6 }, 1200);
  })
  .onLabelClick(d => {
    showCountryDetail(d.code);
    world.pointOfView({ lat: d.lat, lng: d.lng, altitude: 1.6 }, 1200);
  });

world(globeEl);

// 适配尺寸
function resizeGlobe() {
  const w = globeEl.clientWidth;
  const h = globeEl.clientHeight;
  world.width(w).height(h);
}
window.addEventListener("resize", resizeGlobe);
resizeGlobe();

// 自动旋转与拖拽手感优化
const controls = world.controls();
controls.autoRotate = true;
controls.autoRotateSpeed = 0.5;
controls.enableDamping = true;
controls.dampingFactor = 0.05; // 降低阻尼，让拖拽更顺滑
controls.rotateSpeed = 0.8;    // 提高旋转灵敏度
controls.zoomSpeed = 1.2;      // 提高缩放灵敏度

// 鼠标交互时暂停自动旋转
globeEl.addEventListener("mousedown", () => { controls.autoRotate = false; });
globeEl.addEventListener("mouseup", () => {
  // 5 秒后恢复自动旋转
  setTimeout(() => { controls.autoRotate = true; }, 5000);
});

// 初始视角
setTimeout(() => {
  world.pointOfView({ lat: 25, lng: 0, altitude: 2.4 }, 0);
}, 100);

// ---------- 工具函数 ----------
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const bigint = parseInt(h, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `${r}, ${g}, ${b}`;
}

// ---------- 渲染国家详情 ----------
function showCountryDetail(code) {
  const data = PUNK_DATA[code];
  if (!data) return;

  document.getElementById("emptyState").classList.add("hidden");
  const detailEl = document.getElementById("countryDetail");
  detailEl.classList.remove("hidden");

  detailEl.innerHTML = `
    <div class="detail-header">
      <div class="detail-tape">★ ${code} ZONE</div>
      <div class="detail-flag-row">
        <div class="detail-flag">${data.flag}</div>
        <div class="detail-name">${data.name}</div>
      </div>
      <div class="detail-scene">${data.scene}</div>
    </div>
    <div class="bands-list">
      ${data.bands.map((band, i) => renderBand(band, i)).join("")}
    </div>
  `;

  // 滚动到顶部
  document.querySelector(".info-panel").scrollTop = 0;

  // 给 song 绑定播放跳转（YouTube 搜索）
  detailEl.querySelectorAll(".song").forEach(el => {
    el.addEventListener("click", () => {
      const q = encodeURIComponent(el.dataset.query);
      window.open(`https://www.youtube.com/results?search_query=${q}`, "_blank");
    });
  });
}

function renderSongMeta(band, song) {
  const metaParts = [];
  if (song.artist && song.artist !== band.name) metaParts.push(song.artist);
  if (song.album) metaParts.push(song.album);
  metaParts.push(song.year || "N/A");
  if (song.isNew) metaParts.push("🆕 新上榜");
  return metaParts.join(" · ");
}

function renderBand(band, idx) {
  return `
    <div class="band-card">
      <div class="band-header">
        <div class="band-name">${band.name}</div>
        <div class="band-tag">${band.tag}</div>
      </div>
      <div class="band-meta">
        <span><span class="material-symbols-outlined" style="font-size:14px">calendar_today</span>${band.era}</span>
        <span><span class="material-symbols-outlined" style="font-size:14px">location_on</span>${band.hometown}</span>
      </div>
      <ul class="songs">
        ${band.songs.map((s, i) => {
          const queryArtist = s.artist || band.name;
          return `
          <li class="song" data-query="${queryArtist} ${s.title}">
            <span class="song-num">${String(i + 1).padStart(2, "0")}</span>
            <span class="song-title">${s.title}</span>
            <span class="song-meta">${renderSongMeta(band, s)}</span>
            <span class="song-play">▶</span>
          </li>
        `;
        }).join("")}
      </ul>
    </div>
  `;
}

// ---------- 快捷按钮 ----------
document.querySelectorAll(".quick-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const code = btn.dataset.country;
    const c = PUNK_DATA[code];
    if (!c) return;
    showCountryDetail(code);
    world.pointOfView({ lat: c.lat, lng: c.lng, altitude: 1.6 }, 1200);
    controls.autoRotate = false;
  });
});

// ---------- 启动小动画：标题打字 ----------
console.log("%c🎸 PUNK PLANET 🌍", "font-family: Bungee; font-size: 28px; color: #ff2d8a; text-shadow: 2px 2px 0 #fff04d;");
console.log("%cMade for 康康 with ❤️ by 牛牛", "font-size:13px;color:#fff04d;");
