document.addEventListener("DOMContentLoaded", () => {
  console.log("🚀 stars.js loaded and DOM ready!");
  const canvas = document.getElementById('starfield');
  if (!canvas) {
    console.error("❌ Canvas #starfield not found!");
    return;
  }

document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById('starfield');
  const ctx = canvas.getContext('2d');

function resizeCanvas() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  console.log("📐 Resized canvas to:", canvas.width, canvas.height);
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

  const stars = Array.from({ length: 150 }).map(() => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    r: Math.random() * 1.5,
    dx: (Math.random() - 0.5) * 0.3,
    dy: (Math.random() - 0.5) * 0.3
  }));

  function drawStars() {
    ctx.fillStyle = "lime";
    ctx.beginPath();
    ctx.arc(200, 200, 20, 0, Math.PI * 2);
    ctx.fill();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = 'white';
    stars.forEach(star => {
      ctx.beginPath();
      ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
      ctx.fill();
      star.x += star.dx;
      star.y += star.dy;

      if (star.x < 0 || star.x > canvas.width) star.dx *= -1;
      if (star.y < 0 || star.y > canvas.height) star.dy *= -1;
    });
    requestAnimationFrame(drawStars);
  }
  drawStars();
});});