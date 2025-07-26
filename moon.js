const moonImages = {
  "New Moon": "images/moon_phases/new.jpg",
  "Waxing Crescent": "images/moon_phases/waxing_crescent.jpg",
  "First Quarter": "images/moon_phases/first_quarter.jpg",
  "Waxing Gibbous": "images/moon_phases/waxing_gibbous.jpg",
  "Full Moon": "images/moon_phases/full.jpg",
  "Waning Gibbous": "images/moon_phases/waning_gibbous.jpg",
  "Last Quarter": "images/moon_phases/last_quarter.jpg",
  "Waning Crescent": "images/moon_phases/waning_crescent.jpg"
};

const apiKey = '611276174672441494e12054252607';
const location = '51.0500,-114.0600'; // Calgary, Canada


fetch(`https://api.weatherapi.com/v1/astronomy.json?key=${apiKey}&q=${location}`)
  .then(res => res.json())
  .then(data => {
    const moon = data.astronomy.astro;
    const phase = moon.moon_phase;
    const image = moonImages[phase] || "images/moon_phases/full.jpg"; // Default to full moon if phase not found

    document.getElementById('moon-info').innerHTML = `
      Phase: <strong>${phase}</strong><br>
      Illumination: ${moon.moon_illumination}%
    `;

    document.getElementById('moon-image').src = image;
    document.getElementById('moon-image').alt = phase;
  })
  .catch(err => {
    console.error('Moon data error:', err);
    document.getElementById('moon-info').textContent = 'Could not load moon data.';
  });

  