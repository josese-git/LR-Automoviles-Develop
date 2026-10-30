const https = require('https');

const options = {
    hostname: 'autosjveloce.com',
    path: '/Coches/detalle.html?id=mini-cooper-cabrio-2012',
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
        console.log(body.substring(0, 1500));
    });
});

req.on('error', (e) => {
    console.error(`problem with request: ${e.message}`);
});

req.end();
