// Vendored from plotly.js-locales@3.7.0 (matches the plotly.js core version
// bundled by the installed Python `plotly` package), adapted for direct
// browser use as a Dash asset: the upstream file is CommonJS
// (`module.exports = {...}`), so the object literal is passed to
// `Plotly.register(...)` instead. Deferred to `window.onload` as a safety
// net in case this asset ever executes before Dash's own plotly.js bundle.
// See PLAN_dashboard_i18n.md step 5.
(function registerLocale() {
    if (typeof Plotly === 'undefined') {
        window.addEventListener('load', registerLocale, { once: true });
        return;
    }
    Plotly.register({
    moduleType: 'locale',
    name: 'nl',
    dictionary: {
        'Autoscale': 'Automatische schaal',
        'Click to enter Colorscale title': 'Klik om kleurenschaal titel in te vullen',
        'Click to enter Component A title': 'Klik om Component A titel in te vullen',
        'Click to enter Component B title': 'Klik om Component B titel in te vullen',
        'Click to enter Component C title': 'Klik om Component C titel in te vullen',
        'Click to enter Plot title': 'Klik om Plot titel in te vullen',
        'Click to enter X axis title': 'Klik om x-as titel in te vullen',
        'Click to enter Y axis title': 'Klik om y-as titel in te vullen',
        'Click to enter radial axis title': 'Klik om radiaal-as titel in te vullen',
        'Double-click to zoom back out': 'Zoom uit door te dubbel klikken',
        'Download plot as a PNG': 'Dowload de plot als een PNG-bestand',
        'Download plot': 'Download de plot',
        'Draw circle': 'Teken cirkel',
        'Draw closed freeform': 'Teken gesloten vorm',
        'Draw line': 'Teken lijn',
        'Draw open freeform': 'Teken open vorm',
        'Draw rectangle': 'Teken rechthoek',
        'Edit in Chart Studio': 'In Chart Studio wijzigen',
        'Erase active shape': 'Wis huidige vorm',
        'IE only supports svg. Changing format to svg.': 'IE ondersteunt alleen svg bestanden. Formaat gewijzigd naar svg.',
        'Lasso Select': 'Lasso selectie',
        'Produced with Plotly.js': 'Gemaakt met Plotly.js',
        'Zoom': 'Inzoomen',
        'max:': 'maximum:',
        'mean ± σ:': 'gemiddelde ± σ:',
        'mean:': 'gemiddelde:',
        'min:': 'minimum:',
        'new text': 'nieuwe tekst',
        'open:': 'openen:',
        'high:': 'hoog:',
        'low:': 'laag:',
        'source:': 'bron:',
        'target:': 'doel:',
    },
    format: {
        days: [
            'zondag', 'maandag', 'dinsdag', 'woensdag',
            'donderdag', 'vrijdag', 'zaterdag'
        ],
        shortDays: ['zo', 'ma', 'di', 'wo', 'do', 'vr', 'za'],
        months: [
            'januari', 'februari', 'maart', 'april', 'mei', 'juni',
            'juli', 'augustus', 'september', 'oktober', 'november', 'december'
        ],
        shortMonths: [
            'jan', 'feb', 'mrt', 'apr', 'mei', 'jun',
            'jul', 'aug', 'sep', 'okt', 'nov', 'dec'
        ],
        date: '%d-%m-%Y',
        decimal: ',',
        thousands: '.',
        year: '%Y',
        month: '%b %Y',
        dayMonth: '%-d %b',
        dayMonthYear: '%-d %b %Y'
    }
});
})();
