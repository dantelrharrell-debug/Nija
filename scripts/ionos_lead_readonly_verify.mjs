#!/usr/bin/env node
/* Offline, read-only verification. Never prints or writes decrypted lead data. */
import fs from 'node:fs';
import {verifyEncryptedExport} from './ionos_lead_readonly_export.mjs';
const argv=process.argv.slice(2);
if(argv.length!==4 || argv[0]!=='--input' || argv[2]!=='--private-key'){
 console.error('Usage: node ionos_lead_readonly_verify.mjs --input ENCRYPTED_EXPORT.json --private-key PRIVATE_KEY.pem');
 process.exitCode=2;
}else {
 try {
  const ciphertext=JSON.parse(fs.readFileSync(argv[1],'utf8'));
  const privateKey=fs.readFileSync(argv[3],'utf8');
  const result=verifyEncryptedExport(ciphertext,privateKey);
  console.log(JSON.stringify({status:'ISOLATED_LOGICAL_EXPORT_VERIFIED_NOT_TRANSACTIONAL_BACKUP',...result}));
 }catch(err){console.error('Verification refused:',err.message);process.exitCode=1;}
}