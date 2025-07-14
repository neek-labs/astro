document.addEventListener("DOMContentLoaded", () => {
  console.log("🚀 stars.js loaded and DOM ready!");
  const canvas = document.getElementById('starfield');
  if (!canvas) {
    console.error("❌ Canvas #starfield not found!");
    return;
  }

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

let hyperspace = true; // Enable streaks at start

setTimeout(() => {
  hyperspace = false; // Disable streaks after 2.2s
}, 2200);

function drawStars() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'white';
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 1;

  stars.forEach(star => {
    if (hyperspace) {
      // Draw a streak line based on velocity
      ctx.beginPath();
      ctx.moveTo(star.x, star.y);
      ctx.lineTo(star.x - star.dx * 40, star.y - star.dy * 40); // hyperspace trail
      ctx.stroke();
    } else {
      // Normal glowing circular stars
      ctx.shadowColor = 'white';
      ctx.shadowBlur = 2;
      ctx.beginPath();
      ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
      ctx.fill();
    }

    star.x += star.dx;
    star.y += star.dy;

    if (star.x < 0 || star.x > canvas.width) star.dx *= -1;
    if (star.y < 0 || star.y > canvas.height) star.dy *= -1;
  });

  requestAnimationFrame(drawStars);
}

drawStars();

document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("hyperspace-overlay");
  if (overlay) {
    setTimeout(() => {
      overlay.style.display = "none";
    }, 2200); // Hide it after animation completes
  }
})});