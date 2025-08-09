const orionBot = (input) => {
  input = input.toLowerCase();
  if (input.includes("sun")) return "The average distance to the Sun is about 149.6 million kilometers.";
  if (input.includes("moon")) return "The Moon is 384,400 km from Earth on average.";
  if (input.includes("black hole")) return "A black hole is a region of spacetime where gravity is so strong, nothing—not even light—can escape.";
  return "I'm still learning that, explorer.";
};

const prompts = [
  "Do you know the distance from Earth to the Sun?",
  "What is the largest planet in our Solar System?",
  "Can we see the Andromeda Galaxy with the naked eye?",
  "What's a black hole?",
];

function toggleOrion() {
  const panel = document.getElementById("orion-terminal");
  panel.classList.toggle("open");
  if (panel.classList.contains("open") && typeof suggestPrompt === "function") {
    suggestPrompt();
  }
}

function sendToOrion() {
  const inputField = document.getElementById("user-input");
  const chatWindow = document.getElementById("chat-window");
  const userText = inputField.value.trim();
  if (!userText) return;

  // Show user message
  const userMsg = document.createElement("p");
  userMsg.className = "user-msg";
  userMsg.textContent = `You: ${userText}`;
  chatWindow.appendChild(userMsg);

  // Get Orion's response
  const reply = orionBot(userText);
  const orionMsg = document.createElement("p");
  orionMsg.className = "orion-msg";
  orionMsg.textContent = `Orion: ${reply}`;
  chatWindow.appendChild(orionMsg);

  inputField.value = "";
  chatWindow.scrollTop = chatWindow.scrollHeight; // Scroll to bottom
}

function suggestPrompt() {
  const inputField = document.getElementById("user-input");
  const randomPrompt = prompts[Math.floor(Math.random() * prompts.length)];
  inputField.placeholder = randomPrompt;
}