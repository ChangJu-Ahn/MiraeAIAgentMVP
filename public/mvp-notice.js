(() => {
  const syncTheme = () => {
    const param = new URLSearchParams(window.location.search).get("scoutTheme");
    const theme = param || (
      document.documentElement.classList.contains("dark") ? "dark" : "light"
    );
    document.documentElement.setAttribute("data-theme", theme);
  };
  syncTheme();
  new MutationObserver(syncTheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });

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

  let dialog;
  let status;
  let list;
  let questions;
  let focusAfterClose;

  const showStatus = (message, error = false) => {
    status.setAttribute("role", error ? "alert" : "status");
    status.textContent = message;
  };

  const fillQuestion = (question) => {
    const input = document.getElementById("chat-input");
    if (!(input instanceof HTMLTextAreaElement) || input.disabled || input.readOnly) {
      showStatus("지금은 입력창을 사용할 수 없습니다. 대화 화면에서 다시 선택해 주세요.", true);
      return;
    }
    if (input.value.trim() && input.value !== question &&
        !window.confirm("작성 중인 질문을 선택한 예시 질문으로 바꿀까요?")) {
      return;
    }

    // Update React's controlled textarea, not only its DOM display.
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(input, question);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    focusAfterClose = input;
    dialog.close();
    input.focus();
    input.setSelectionRange(question.length, question.length);
  };

  const renderQuestions = () => {
    list.replaceChildren();
    for (const item of questions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "question-example";
      const number = document.createElement("span");
      number.className = "question-example-number";
      number.textContent = item.id;
      const text = document.createElement("span");
      text.textContent = item.question;
      button.append(number, text);
      button.addEventListener("click", () => fillQuestion(item.question));
      list.append(button);
    }
    showStatus(questions.length ? `Evaluation 질문 ${questions.length}개` : "등록된 질문 예시가 없습니다.");
  };

  const createDialog = () => {
    dialog = document.createElement("dialog");
    dialog.id = "question-examples-dialog";
    dialog.setAttribute("aria-labelledby", "question-examples-title");
    dialog.setAttribute("aria-describedby", "question-examples-description");
    dialog.innerHTML = `
      <div class="question-examples-heading">
        <h2 id="question-examples-title">질문 예시</h2>
        <button type="button" class="question-examples-close" aria-label="질문 예시 닫기">닫기</button>
      </div>
      <p id="question-examples-description">질문을 고르면 입력창에 채워집니다. 수정한 뒤 직접 전송해 주세요.</p>
      <p class="question-examples-note">기금 보고서 기준의 평가 질문입니다. 자료 부재를 확인하는 질문도 포함되어 있으며, 답변은 현재 적재된 문서를 검색해 생성합니다.</p>
      <p id="question-examples-status" role="status" aria-live="polite"></p>
      <div class="question-examples-list"></div>
    `;
    status = dialog.querySelector("#question-examples-status");
    list = dialog.querySelector(".question-examples-list");
    dialog.querySelector(".question-examples-close").addEventListener("click", () => dialog.close());
    // Chainlit shortcuts can cancel the browser's default Escape handling.
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      dialog.close();
    });
    dialog.addEventListener("close", () => {
      if (focusAfterClose?.isConnected) focusAfterClose.focus();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right ||
          event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    document.body.append(dialog);
  };

  const openQuestions = async (trigger) => {
    if (!dialog) createDialog();
    if (dialog.open) return;
    focusAfterClose = trigger;
    dialog.showModal();
    if (questions) {
      renderQuestions();
      return;
    }
    showStatus("질문 예시를 불러오는 중입니다.");
    try {
      const response = await fetch("/public/evaluation-data.json", { cache: "no-cache" });
      if (!response.ok) throw new Error(`Evaluation HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.rows) || data.rows.some(row =>
        !row || typeof row.id !== "string" || typeof row.question !== "string" ||
        !row.question.trim()
      )) throw new Error("Invalid Evaluation question data");
      questions = data.rows.map(row => ({ id: row.id, question: row.question }));
      renderQuestions();
    } catch (error) {
      console.error("Could not load question examples", error);
      showStatus("질문 예시를 불러오지 못했습니다. 닫고 다시 열어 주세요.", true);
    }
  };

  const mountPicker = () => {
    const composer = document.getElementById("message-composer");
    let toolbar = document.getElementById("question-examples-toolbar");
    if (!composer) {
      toolbar?.remove();
      return;
    }
    if (toolbar?.nextElementSibling === composer) return;
    if (!toolbar) {
      toolbar = document.createElement("div");
      toolbar.id = "question-examples-toolbar";
      const button = document.createElement("button");
      button.id = "question-examples-trigger";
      button.type = "button";
      button.setAttribute("aria-haspopup", "dialog");
      button.setAttribute("aria-controls", "question-examples-dialog");
      const icon = document.createElement("img");
      icon.src = "/public/question-examples.svg";
      icon.alt = "";
      icon.width = 20;
      icon.height = 20;
      button.append(icon, "질문 예시");
      button.addEventListener("click", () => openQuestions(button));
      toolbar.append(button);
    }
    composer.before(toolbar);
  };

  const watchComposer = () => {
    mountPicker();
    let scheduled = false;
    new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        mountPicker();
      });
    }).observe(document.getElementById("root") || document.body, {
      childList: true,
      subtree: true,
    });
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watchComposer, { once: true });
  } else {
    watchComposer();
  }
})();