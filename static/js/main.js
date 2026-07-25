// main.js — enhancement kecil untuk UX (bukan fitur inti)
document.addEventListener("DOMContentLoaded", () => {
  // Auto-hide flash messages setelah 5 detik
  document.querySelectorAll(".flash").forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity .4s ease";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 400);
    }, 5000);
  });

  // Preview nama file yang dipilih pada input foto
  const photoInput = document.getElementById("photo");
  if (photoInput) {
    photoInput.addEventListener("change", () => {
      const hint = photoInput.parentElement.querySelector(".field-hint");
      if (hint && photoInput.files.length) {
        hint.textContent = `File dipilih: ${photoInput.files[0].name}`;
      }
    });
  }
});
