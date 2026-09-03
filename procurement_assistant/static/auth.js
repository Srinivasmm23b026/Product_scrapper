const authForm = (id, handler) => {
  const form = document.querySelector(id);
  if (form) form.addEventListener("submit", handler);
};

document.addEventListener("DOMContentLoaded", () => {
  let pendingEmail = "";
  authForm("#signup-form", async event => {
    event.preventDefault();
    pendingEmail = document.querySelector("#signup-email").value;
    try {
      await api("/auth/signup", {method: "POST", body: JSON.stringify({
        email: pendingEmail,
        password: document.querySelector("#signup-password").value,
      })});
      toast("Verification code sent.");
    } catch (error) { toast(error.message); }
  });
  authForm("#confirm-form", async event => {
    event.preventDefault();
    if (!pendingEmail) { toast("Enter your email in Create an account first."); return; }
    try {
      await api("/auth/confirm", {method: "POST", body: JSON.stringify({
        email: pendingEmail, code: document.querySelector("#confirm-code").value,
      })});
      toast("Email verified. You can sign in.");
    } catch (error) { toast(error.message); }
  });
  authForm("#forgot-form", async event => {
    event.preventDefault();
    pendingEmail = document.querySelector("#forgot-email").value;
    try {
      await api("/auth/forgot-password", {method: "POST", body: JSON.stringify({email: pendingEmail})});
      toast("Password reset code sent.");
    } catch (error) { toast(error.message); }
  });
  authForm("#reset-form", async event => {
    event.preventDefault();
    if (!pendingEmail) { toast("Enter your email in Forgot password first."); return; }
    try {
      await api("/auth/reset-password", {method: "POST", body: JSON.stringify({
        email: pendingEmail,
        code: document.querySelector("#reset-code").value,
        password: document.querySelector("#reset-password").value,
      })});
      toast("Password reset. You can sign in.");
    } catch (error) { toast(error.message); }
  });
});
