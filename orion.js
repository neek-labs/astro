const orionBot = (input) => {
  input = input.toLowerCase();
  if (input.includes("sun")) return "The average distance to the Sun is about 149.6 million kilometers.";
  if (input.includes("moon")) return "The Moon is 384,400 km from Earth on average.";
  return "I'm still learning that, explorer.";
};

const prompts = [
  "Do you know the distance from Earth to the Sun?",
  "What is the largest planet in our Solar System?",
  "Can we see the Andromeda Galaxy with the naked eye?",
  "What's a black hole?",
];
