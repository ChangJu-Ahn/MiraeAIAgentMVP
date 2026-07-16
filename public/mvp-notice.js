(() => {
  const mountNotice = () => {
    let notice = document.getElementById("mvp-notice");

    if (!notice) {
      notice = document.createElement("aside");
      notice.id = "mvp-notice";
      notice.setAttribute("role", "note");
      notice.setAttribute("aria-label", "MVP 서비스 안내");

      const label = document.createElement("strong");
      label.textContent = "MVP 안내:";
      notice.append(
        label,
        " 기능 검증용 PoC이며 Production 운영용 서비스가 아닙니다.",
      );
      document.body.prepend(notice);
    }

    document.body.classList.add("mvp-notice-active");
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountNotice, { once: true });
  } else {
    mountNotice();
  }
})();