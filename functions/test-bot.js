const https = require('https');

const options = {
    hostname: 'jveloce-cf602.web.app',
    path: '/Coches/detalle.html?id=volkswagen-passat-variant-2015',
    method: 'GET',
    headers: {
        'User-Agent': 'WhatsApp/2.21.12.21 A'
    }
};

const req = https.request(options, (res) => {
    console.log(`STATUS: ${res.statusCode}`);
    console.log(`HEADERS: ${JSON.stringify(res.headers)}`);
    res.setEncoding('utf8');
    let body = '';
    res.on('data', (chunk) => {
        body += chunk;
    });
    res.on('end', () => {
        console.log('BODY:');
        console.log(body.substring(0, 1000));
    });
});

req.on('error', (e) => {
    console.error(`problem with request: ${e.message}`);
});

req.end();
